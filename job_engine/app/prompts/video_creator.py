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


def public_download_url(key: str) -> str:
    """Browser Save-As URL — not the play/stream URL Gemini uses."""
    return f'{public_url(key)}?download=1'


def as_download_url(url: str | None) -> str:
    text = (url or '').strip()
    if not text:
        return ''
    if 'download=1' in text or text.rstrip('/').endswith('/download'):
        return text
    return f"{text}{'&' if '?' in text else '?'}download=1"


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


TERMINAL_STATES = ('succeeded', 'failed', 'canceled')
POLL_S = 5.0
# Consecutive poll errors (home Wi-Fi blips) tolerated before giving up
POLL_ERRORS_TOLERATED = 12


def _create_prediction(client, model: str, inputs: dict):
    """Start the prediction WITHOUT `Prefer: wait`. `client.run()` blocks the
    HTTP call with a 60.5 s read timeout while the server holds the
    connection for up to 60 s — a 10 s Kling render takes minutes, so both
    #29 renders died with 'The read operation timed out' (2026-09-10)
    before the model had even finished."""
    ref, _, version_id = model.partition(':')
    if version_id:
        return client.predictions.create(version=version_id, input=inputs)
    return client.models.predictions.create(model=ref, input=inputs)


def replicate_render(client, model: str, *, input: dict, budget_s: float, poll_s: float = POLL_S, sleep=None, log=None):
    """Create → poll every `poll_s` until a terminal state or `budget_s`
    elapses (then cancel, so no orphan keeps billing). Returns the output
    URL(s). Raises RuntimeError with the model's own error text."""
    import time as _time

    sleep = sleep or _time.sleep
    prediction = _create_prediction(client, model, input)
    started = _time.monotonic()
    errors = 0
    last_status = None
    while prediction.status not in TERMINAL_STATES:
        if prediction.status != last_status:
            last_status = prediction.status
            if log:
                log(f'video model {model} prediction {prediction.id}: {prediction.status}')
        if _time.monotonic() - started > budget_s:
            stuck_in = prediction.status
            try:
                prediction.cancel()
            except Exception:  # best effort — the budget is the promise
                pass
            raise RuntimeError(f'video model still {stuck_in} after {int(budget_s)}s — cancelled')
        sleep(poll_s)
        try:
            prediction.reload()
            errors = 0
        except Exception as exc:
            errors += 1
            if errors >= POLL_ERRORS_TOLERATED:
                raise RuntimeError(f'lost contact with the video model ({exc})') from exc
    if prediction.status != 'succeeded':
        raise RuntimeError(f'video model {prediction.status}: {prediction.error or "no reason given"}')
    if prediction.output in (None, [], ''):
        raise RuntimeError('video model succeeded but returned no file')
    return prediction.output


def create_video(
    prompt_text: str,
    product_image: Path,
    *,
    prompt_id: int,
    aspect_ratio: str = '9:16',
    duration_s: int | None = None,
    run=None,
    log=None,
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
        budget_s = float(getattr(config, 'PROMPT_VIDEO_TIMEOUT_S', 900))

        def run(model, input):  # noqa: A001 — mirrors client.run's shape
            return replicate_render(client, model, input=input, budget_s=budget_s, log=log)

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


@dataclass
class ReelAsset:
    reel_key: str
    reel_path: Path
    reel_url: str
    frames: int
    duration_s: float
    engine: str = 'ffmpeg'


def create_reel(
    video_path: Path,
    *,
    prompt_id: int,
    prompt_text: str,
    keyword: str,
    title: str | None = None,
    handle: str = '@jobmaster.agency',
    kind: str = 'reel',
) -> ReelAsset:
    """Raw clip → post-ready reel MP4 in the asset root (header · 9:16 clip ·
    storyboard | scrolling prompt · hardcoded footer). Raises post_reel.ReelError
    with an operator-readable reason — the caller keeps the raw clip."""
    from app.prompts import post_reel

    key = asset_key(kind, prompt_id=prompt_id, suffix='mp4')
    target = assets_root() / key
    tmp = target.with_name(target.name + '.part.mp4')
    result = post_reel.compose_reel(
        video_path, tmp, prompt_text=prompt_text, keyword=keyword,
        title=title, handle=handle,
    )
    tmp.replace(target)
    meta = assets_root() / '.meta' / key
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text('video/mp4', encoding='utf-8')
    return ReelAsset(
        reel_key=key, reel_path=target, reel_url=public_url(key),
        frames=result.frames, duration_s=result.duration_s, engine=result.engine,
    )
