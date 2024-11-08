import os
import time
import requests
import traceback
import json
import base64
import uuid
import runpod
from runpod.serverless.utils.rp_validator import validate
from runpod.serverless.modules.rp_logger import RunPodLogger
from requests.adapters import HTTPAdapter, Retry
from schemas.input import INPUT_SCHEMA
from google.cloud import storage

BASE_URI = 'http://127.0.0.1:3000'
VOLUME_MOUNT_PATH = '/runpod-volume'
TIMEOUT = 600
LOG_LEVEL = 'INFO'

session = requests.Session()
retries = Retry(total=10, backoff_factor=0.1, status_forcelist=[502, 503, 504])
session.mount('http://', HTTPAdapter(max_retries=retries))
logger = RunPodLogger()


# ---------------------------------------------------------------------------- #
#                               ComfyUI Functions                              #
# ---------------------------------------------------------------------------- #

def wait_for_service(url):
    retries = 0

    while True:
        try:
            requests.get(url)
            return
        except requests.exceptions.RequestException:
            retries += 1

            # Only log every 15 retries so the logs don't get spammed
            if retries % 15 == 0:
                logger.info('Service not ready yet. Retrying...')
        except Exception as err:
            logger.error(f'Error: {err}')

        time.sleep(0.2)


def send_get_request(endpoint):
    return session.get(
        url=f'{BASE_URI}/{endpoint}',
        timeout=TIMEOUT
    )


def send_post_request(endpoint, payload):
    return session.post(
        url=f'{BASE_URI}/{endpoint}',
        json=payload,
        timeout=TIMEOUT
    )

def get_txt2img_payload(workflow, payload):
    workflow["3"]["inputs"]["seed"] = payload["seed"]
    workflow["3"]["inputs"]["steps"] = payload["steps"]
    workflow["3"]["inputs"]["cfg"] = payload["cfg_scale"]
    workflow["3"]["inputs"]["sampler_name"] = payload["sampler_name"]
    workflow["4"]["inputs"]["ckpt_name"] = payload["ckpt_name"]
    workflow["5"]["inputs"]["batch_size"] = payload["batch_size"]
    workflow["5"]["inputs"]["width"] = payload["width"]
    workflow["5"]["inputs"]["height"] = payload["height"]
    workflow["6"]["inputs"]["text"] = payload["prompt"]
    workflow["7"]["inputs"]["text"] = payload["negative_prompt"]
    return workflow


def get_img2img_payload(workflow, payload):
    workflow["13"]["inputs"]["seed"] = payload["seed"]
    workflow["13"]["inputs"]["steps"] = payload["steps"]
    workflow["13"]["inputs"]["cfg"] = payload["cfg_scale"]
    workflow["13"]["inputs"]["sampler_name"] = payload["sampler_name"]
    workflow["13"]["inputs"]["scheduler"] = payload["scheduler"]
    workflow["13"]["inputs"]["denoise"] = payload["denoise"]
    workflow["1"]["inputs"]["ckpt_name"] = payload["ckpt_name"]
    workflow["2"]["inputs"]["width"] = payload["width"]
    workflow["2"]["inputs"]["height"] = payload["height"]
    workflow["2"]["inputs"]["target_width"] = payload["width"]
    workflow["2"]["inputs"]["target_height"] = payload["height"]
    workflow["4"]["inputs"]["width"] = payload["width"]
    workflow["4"]["inputs"]["height"] = payload["height"]
    workflow["4"]["inputs"]["target_width"] = payload["width"]
    workflow["4"]["inputs"]["target_height"] = payload["height"]
    workflow["6"]["inputs"]["text"] = payload["prompt"]
    workflow["7"]["inputs"]["text"] = payload["negative_prompt"]
    return workflow


def get_im2imbase_payload(workflow, payload):
    workflow["182"]["inputs"]["image"] = payload["image"]
    workflow["180"]["inputs"]["value"] = payload["resemblance"]    
    workflow["152"]["inputs"]["width"] = payload["width"]
    workflow["152"]["inputs"]["height"] = payload["height"]
    workflow["102"]["inputs"]["noise_seed"] = payload["seed"]

    return workflow


def get_product_alt_payload(workflow, payload):
    workflow["177"]["inputs"]["image"] = payload['alpha']
    workflow["178"]["inputs"]["image"] = payload['depth']
    workflow["179"]["inputs"]["image"] = payload['mask']
    workflow["179"]["inputs"]["text"] = payload['prompt']
    workflow["21"]["inputs"]["seed"] = payload["seed"]
    workflow["131"]["inputs"]["noise_seed"] = payload["seed"]
    workflow["137"]["inputs"]["noise_seed"] = payload["seed"]
    return workflow


def get_txt2imbase_payload(workflow, payload):
    workflow["5"]["inputs"]["width"] = payload["width"]
    workflow["5"]["inputs"]["height"] = payload["height"]
    workflow["73"]["inputs"]["text_2"] = payload["subject"]
    workflow["73"]["inputs"]["text_3"] = payload["scene"]
    workflow["73"]["inputs"]["text_4"] = payload["style"]

    workflow["25"]["inputs"]["noise_seed"] = payload["seed"]
    workflow["82"]["inputs"]["noise_seed"] = payload["seed"]
    return workflow

def get_inpaint_payload(workflow, payload):
    workflow["185"]["inputs"]["image"] = payload["image"]
    workflow["187"]["inputs"]["mask"] = payload["mask"]

    workflow["52"]["inputs"]["noise_seed"] = payload["seed"]
    workflow["45"]["inputs"]["text"] = payload["prompt"]
    if 'negative_prompt' in payload and payload['negative_prompt']:
        workflow["57"]["inputs"]["text"] = payload["negative_prompt"]

    return workflow


def get_workflow_payload(workflow_name, payload):
    with open(f'/workflows/{workflow_name}.json', 'r') as json_file:
        workflow = json.load(json_file)

    if workflow_name == 'txt2img':
        workflow = get_txt2img_payload(workflow, payload)
    elif workflow_name == 'im2im_base':
        workflow = get_im2imbase_payload(workflow, payload)
    elif workflow_name == 'product_alt':
        workflow = get_product_alt_payload(workflow, payload)
    elif workflow_name == 'txt2im_base':
        workflow = get_txt2imbase_payload(workflow, payload)
    elif workflow_name == 'inpaint':
        workflow = get_inpaint_payload(workflow, payload)

    return workflow


"""
Get the filenames of the output images
"""
def get_filenames(output):
    for key, value in output.items():
        if 'images' in value and isinstance(value['images'], list):
            return value['images']


"""
Create a unique filename prefix for each request to avoid a race condition where
more than one request completes at the same time, which can either result in the
incorrect output being returned, or the output image not being found.
"""
def create_unique_filename_prefix(payload):
    for key, value in payload.items():
        class_type = value.get('class_type')

        if class_type == 'SaveImage':
            payload[key]['inputs']['filename_prefix'] = str(uuid.uuid4())


def upload_output_to_gcs(imid, image, model=None):    
    print('Uploading to GCS')
    prefix = image.split('/')[-1].split('_')[0]
    storagecredfile = os.path.join(os.path.dirname(__file__), 'leafhome-backend-4eaca2289782.json')
    storage_client = storage.Client.from_service_account_json(storagecredfile)    
    bucket = storage_client.bucket("addition-leafhome-generations")
    if model is not None:
        prefix = f'{model}_{prefix}'
    blob = bucket.blob(f'output/{prefix}_{imid}.png')
    blob.upload_from_filename(image)
    os.remove(image)
    return blob.public_url



# ---------------------------------------------------------------------------- #
#                                RunPod Handler                                #
# ---------------------------------------------------------------------------- #
def handler(event):
    job_id = event['id']

    try:
        validated_input = validate(event['input'], INPUT_SCHEMA)

        if 'errors' in validated_input:
            return {
                'error': '\n'.join(validated_input['errors'])
            }

        payload = validated_input['validated_input']
        workflow_name = payload['workflow']
        payload = payload['payload']

        if workflow_name == 'default':
            workflow_name = 'txt2img'

        logger.info(f'Workflow: {workflow_name}', job_id)

        if workflow_name != 'custom':
            try:
                payload = get_workflow_payload(workflow_name, payload)
            except Exception as e:
                logger.error(f'Unable to load workflow payload for: {workflow_name}', job_id)
                raise

        create_unique_filename_prefix(payload)
        logger.debug('Queuing prompt', job_id)

        queue_response = send_post_request(
            'prompt',
            {
                'prompt': payload
            }
        )

        if queue_response.status_code == 200:
            resp_json = queue_response.json()
            prompt_id = resp_json['prompt_id']
            logger.info(f'Prompt queued successfully: {prompt_id}', job_id)
            retries = 0

            while True:
                # Only log every 15 retries so the logs don't get spammed
                if retries == 0 or retries % 15 == 0:
                    logger.info(f'Getting status of prompt: {prompt_id}', job_id)

                r = send_get_request(f'history/{prompt_id}')
                resp_json = r.json()

                if r.status_code == 200 and len(resp_json):
                    break

                time.sleep(0.2)
                retries += 1

            if len(resp_json[prompt_id]['outputs']):                
                resp_json = resp_json[prompt_id]
                logger.info(f"responsejson is type: {type(resp_json)}")
                logger.info(f"respjson keys: {list(resp_json.keys())}")
                logger.info(resp_json)
                logger.info(f'Image generated successfully for prompt: {prompt_id}')
                result = []
                resp_json['uploaded_images'] = []
                for k, v in resp_json['outputs'].items():
                    if 'files' in v:
                        filename = v['files'][0]                    
                        public_url = upload_output_to_gcs(prompt_id, filename)                    
                        resp_json['uploaded_images'].append(public_url)   
                
                return {
                    "results": resp_json,
                }
            else:
                logger.info(f'Response JSON: {resp_json}', job_id)
                raise RuntimeError(f'No output found for prompt id {prompt_id}, please ensure that the model is correct and that it exists')
        else:
            try:
                queue_response_content = queue_response.json()
            except Exception as e:
                queue_response_content = str(queue_response.content)

            logger.error(f'HTTP Status code: {queue_response.status_code}', job_id)
            logger.error(queue_response_content, job_id)

            return {
                'error': f'HTTP status code: {queue_response.status_code}',
                'output': queue_response_content
            }
    except Exception as e:
        logger.error(f'An exception was raised: {e}', job_id)

        return {
            'error': traceback.format_exc(),
            'refresh_worker': True
        }


if __name__ == '__main__':
    logger.set_level(LOG_LEVEL)
    wait_for_service(url=f'{BASE_URI}/system_stats')
    logger.info('ComfyUI API is ready')
    logger.info('Starting RunPod Serverless...')
    runpod.serverless.start(
        {
            'handler': handler
        }
    )
