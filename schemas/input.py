INPUT_SCHEMA = {
    'workflow': {
        'type': str,
        'required': False,
        'default': 'txt2img',
        'constraints': lambda workflow: workflow in [
            'default',
            'txt2img',
            'txt2im_base',
            'im2im_base',
            'inpaint',
            'product_alt'
        ]
    },
    'payload': {
        'type': dict,
        'required': True
    }
}
