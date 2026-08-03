"""Shared Replicate image generation (default: google/imagen-4-fast)."""

from __future__ import annotations

import urllib.request
from io import BytesIO

from PIL import Image

from app import config


def generate_image(prompt: str, *, aspect_ratio: str = '1:1') -> Image.Image:
    import replicate

    token = config.REPLICATE_API_TOKEN
    if not token:
        raise RuntimeError('REPLICATE_API_TOKEN missing in job_engine/.env')

    client = replicate.Client(api_token=token)
    model = config.REPLICATE_MODEL
    # imagen-4-fast schema; flux also accepts aspect_ratio
    inp = {
        'prompt': prompt,
        'aspect_ratio': aspect_ratio,
        'output_format': 'png',
        'safety_filter_level': 'block_only_high',
    }
    # flux-schnell extras (ignored by imagen if unknown? safer to branch)
    if 'flux' in model.lower():
        inp['num_outputs'] = 1
        inp['go_fast'] = True
        inp.pop('safety_filter_level', None)

    output = client.run(model, input=inp)
    item = output[0] if isinstance(output, list) else output
    if hasattr(item, 'read'):
        data = item.read()
    else:
        with urllib.request.urlopen(str(item), timeout=120) as resp:
            data = resp.read()
    return Image.open(BytesIO(data)).convert('RGB')
