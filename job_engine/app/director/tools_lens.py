"""LENS + COURIER — DIRECTOR-written visual prompts → Grok Imagine → Telegram."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agents import function_tool

from app import config
from app.prompt_dictionary import MIN_PROMPT_CHARS, assert_visual_prompt
from app.replicate_img import generate_image

TZ = ZoneInfo('Asia/Kolkata')
TMP = config.BASE_DIR / '.data' / 'director_frames'
LAST_SEND = TMP / 'last_send.json'
LAST_PROMPT = TMP / 'last_prompt.txt'


def _hermes_env() -> dict[str, str]:
    env_path = Path.home() / '.hermes' / '.env'
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    for ln in env_path.read_text(encoding='utf-8').splitlines():
        if not ln or ln.lstrip().startswith('#') or '=' not in ln:
            continue
        k, v = ln.split('=', 1)
        out[k.strip()] = v.strip()
    return out


def send_image_bytes_prompt(prompt: str, *, city: str = '') -> bool:
    """Render a pure visual prompt after VALIDATOR checks embedded numbers."""
    from app.director.tools_validator import run_validator
    from app.director.tools_courier import send_telegram_text
    env = _hermes_env()
    token = env.get('TELEGRAM_BOT_TOKEN')
    chat = os.getenv('DIRECTOR_TARGET_CHAT') or env.get('TELEGRAM_HOME_CHANNEL')
    if not token or not chat:
        return False
    prompt = assert_visual_prompt(prompt)
    verdict = run_validator('visual_prompt', json.dumps({'prompt': prompt}), city)
    if not verdict.get('approved'):
        send_telegram_text(
            'Still verifying… image prompt had numbers that do not match live tower. Retrying.'
        )
        raise ValueError('validator_blocked: ' + '; '.join(verdict.get('errors') or [])[:240])
    TMP.mkdir(parents=True, exist_ok=True)
    LAST_PROMPT.write_text(prompt, encoding='utf-8')
    img = generate_image(prompt, aspect_ratio='1:1')
    path = TMP / f"frame-{datetime.now(TZ).strftime('%H%M%S')}.png"
    img.save(path, format='PNG', optimize=True)
    import sys
    sys.path.insert(0, str(config.BASE_DIR / 'scripts'))
    from telegram_watch_tower import send_photo  # noqa: WPS433
    ok = send_photo(token, chat, path, caption='')
    path.unlink(missing_ok=True)
    if ok:
        LAST_SEND.write_text(
            json.dumps({
                'ts': datetime.now(TZ).isoformat(),
                'ok': True,
                'chars': len(prompt),
                'prompt_file': str(LAST_PROMPT),
                'model': config.REPLICATE_MODEL,
                'validated': True,
            }),
            encoding='utf-8',
        )
    return ok


def send_simple_frame(_line1: str, _line2: str, prompt: str) -> bool:
    return send_image_bytes_prompt(prompt)


@function_tool
def craft_punchline_prompt(prompt: str) -> str:
    """Validate DIRECTOR's Replicate image prompt before render.
    Must be >= MIN_PROMPT_CHARS and a PURE visual description (scene, colors, shapes,
    lighting, exact short on-image words + live fact). Do NOT paste Jarvis policy /
    style-brief essays into the prompt. Returns JSON {ok, chars} or error."""
    try:
        p = assert_visual_prompt(prompt)
    except ValueError as e:
        return json.dumps({
            'ok': False,
            'error': str(e),
            'min_chars': MIN_PROMPT_CHARS,
            'got': len((prompt or '').strip()),
        })
    return json.dumps({'ok': True, 'chars': len(p), 'min_chars': MIN_PROMPT_CHARS})


@function_tool
def lens_render_and_courier_send(prompt: str, city: str = '') -> str:
    """LENS + COURIER: Render with Google Nano Banana 2 and send Telegram photo.
    VALIDATOR blocks prompts that embed unauthenticated KPI numbers.
    Prefer fact boards for any chart/count/list."""
    try:
        ok = send_image_bytes_prompt(prompt, city=city)
    except ValueError as e:
        return json.dumps({'ok': False, 'error': str(e), 'min_chars': MIN_PROMPT_CHARS})
    return json.dumps({
        'ok': ok,
        'delivered': 'telegram_photo' if ok else 'failed',
        'model': config.REPLICATE_MODEL,
    })
