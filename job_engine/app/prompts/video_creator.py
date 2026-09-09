"""Video creator — approved prompt + product image → AI video → asset URL.

The render runs on Replicate (image-to-video; model from
REPLICATE_VIDEO_MODEL) and the MP4 lands in the same asset root AvatarPitch
uses, so it is served publicly at /api/partner/v1/assets/{key} with Range
support for iPhone playback. Keys are random-suffixed (capability URLs).
"""

from __future__ import annotations

import logging
import re
import secrets
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

SAFE_KEY_CHARS = re.compile(r'[^a-z0-9_.-]+')
DOWNLOAD_TIMEOUT_S = 600


@dataclass
class RenderResult:
    video_key: str
    video_path: Path
    video_url: str
    model: str


def assets_root() -> Path:
    from app import config

    return Path(getattr(config, 'PARTNER_ASSETS_DIR', '/srv/avatarpitch/uploads'))


def public_url(key: str) -> str:
    from app import config

    base = (getattr(config, 'PARTNER_PUBLIC_BASE_URL', '') or '').rstrip('/')
    return f'{base}/api/partner/v1/assets/{key}'


def asset_key(kind: str, *, prompt_id: int, suffix: str) -> str:
    """prompts/<utc-day>/<kind>-<prompt>-<random>.<suffix> — passes the
    partner assets key whitelist (lowercase, no dot-leading segments)."""
    from app import config

    prefix = (getattr(config, 'PROMPT_ASSET_PREFIX', 'prompts') or 'prompts').strip('/')
    day = datetime.now(timezone.utc).strftime('%Y%m%d')
    token = secrets.token_hex(6)
    kind = SAFE_KEY_CHARS.sub('-', kind.lower()).strip('-') or 'asset'
    suffix = SAFE_KEY_CHARS.sub('', suffix.lower().lstrip('.')) or 'bin'
    return f'{prefix}/{day}/{kind}-{int(prompt_id)}-{token}.{suffix}'


def store_bytes(key: str, data: bytes, *, content_type: str | None = None) -> Path:
    root = assets_root()
    target = root / key
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + '.part')
    tmp.write_bytes(data)
    tmp.replace(target)
    if content_type:
        meta = root / '.meta' / key
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(content_type, encoding='utf-8')
    return target


def build_input(model: str, prompt: str, image_path: Path, *, duration_s: int, aspect_ratio: str) -> dict:
    """Per-model input shape. Image is passed as a file handle so the
    Replicate client uploads it (no public URL needed)."""
    low = model.lower()
    handle = image_path.open('rb')
    if 'kling' in low:
        return {
            'prompt': prompt,
            'start_image': handle,
            'duration': 10 if duration_s >= 8 else 5,
            'mode': 'standard',
            'negative_prompt': 'text, watermark, logo change, distorted packaging, extra objects',
        }
    if 'veo' in low:
        return {
            'prompt': prompt,
            'image': handle,
            'aspect_ratio': aspect_ratio if aspect_ratio in {'9:16', '16:9'} else '9:16',
            'duration': 8,
            'resolution': '1080p',
        }
    if 'seedance' in low:
        return {
            'prompt': prompt,
            'image': handle,
            'duration': max(5, min(10, duration_s)),
            'aspect_ratio': aspect_ratio,
            'resolution': '1080p',
        }
    if 'minimax' in low or 'hailuo' in low:
        return {'prompt': prompt, 'first_frame_image': handle}
    if 'wan' in low:
        return {'prompt': prompt, 'image': handle, 'aspect_ratio': aspect_ratio}
    return {'prompt': prompt, 'image': handle}


def _read_output(output) -> bytes:
    item = output[0] if isinstance(output, (list, tuple)) else output
    if hasattr(item, 'read'):
        return item.read()
    with urllib.request.urlopen(str(item), timeout=DOWNLOAD_TIMEOUT_S) as resp:
        return resp.read()


def create_video(
    prompt_text: str,
    product_image: Path,
    *,
    prompt_id: int,
    aspect_ratio: str = '9:16',
    duration_s: int | None = None,
    run=None,
) -> RenderResult:
    """Render one video. `run(model, input) -> output` is injectable so the
    task and tests never need a Replicate token."""
    from app import config

    model = getattr(config, 'REPLICATE_VIDEO_MODEL', 'kwaivgi/kling-v2.1')
    duration_s = int(duration_s or getattr(config, 'PROMPT_VIDEO_DURATION_S', 10))
    if run is None:
        token = getattr(config, 'REPLICATE_API_TOKEN', '')
        if not token:
            raise RuntimeError('REPLICATE_API_TOKEN missing in job_engine/.env')
        import replicate

        client = replicate.Client(api_token=token)
        run = client.run
    inputs = build_input(model, prompt_text, product_image, duration_s=duration_s, aspect_ratio=aspect_ratio)
    try:
        output = run(model, input=inputs)
    finally:
        for value in inputs.values():
            if hasattr(value, 'close'):
                value.close()
    data = _read_output(output)
    if len(data) < 1024:
        raise RuntimeError('video model returned an empty file')
    key = asset_key('video', prompt_id=prompt_id, suffix='mp4')
    path = store_bytes(key, data, content_type='video/mp4')
    return RenderResult(video_key=key, video_path=path, video_url=public_url(key), model=model)
