import random
import base64
from util import post_request


def encode_image_to_base64(image_path):
    with open(image_path, "rb") as img_file:
        b64_string = base64.b64encode(img_file.read()).decode('utf-8')
    return b64_string

def main():
    alpha = encode_image_to_base64("/Users/rickbarber/Downloads/RO TankedRO AlphaSys High_001.png")
    depth = encode_image_to_base64("/Users/rickbarber/Downloads/RO Tanked DepthRO Sys High_001.png")
    mask = encode_image_to_base64("/Users/rickbarber/Downloads/RO Tanked MatteRO Sys High_001.png")
    background = encode_image_to_base64("/Users/rickbarber/Downloads/Kitchen Counter_00001_.png")
    #image = encode_image_to_base64("/Users/rickbarber/Downloads/5a8169226e259f26e3d58081c804fab0.jpeg")
    #mask = encode_image_to_base64("/Users/rickbarber/Downloads/mask.png")
    image = encode_image_to_base64("/Users/rickbarber/Downloads/input.png")
    payload = {
        "input": {
            "workflow": "product_alt",
            "payload":
            {
                "seed": random.randrange(1, 1000000),                
                "prompt": "put the product on a marble counter in a modern kitchen",
                "mask": mask,
                "alpha": alpha,
                "depth": depth,
            }
        }
    }
    result = post_request(payload)
    #prompt = ''.join(result['output']['results']['outputs']['487']['INPUT'])
    img_result = result['output']['results']['uploaded_images']
    print(result)

if __name__ == '__main__':
    main()