"""LENS + COURIER — DIRECTOR-written prompts → Grok Imagine → Telegram (no Pillow cards)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agents import function_tool

from app import config
from app.prompt_dictionary import MIN_PROMPT_CHARS, assert_prompt_length
from app.replicate_img import generate_image

TZ = ZoneInfo('Asia/Kolkata')
TMP = config.BASE_DIR / '.data' / 'director_frames'
LAST_SEND = TMP / 'last_send.json'


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


def send_image_bytes_prompt(prompt: str) -> bool:
    """Render prompt as-is (text must be designed into the graphic by the model)."""
    env = _hermes_env()
    token = env.get('TELEGRAM_BOT_TOKEN')
    chat = env.get('TELEGRAM_HOME_CHANNEL')
    if not token or not chat:
        return False
    prompt = assert_prompt_length(prompt)
    img = generate_image(prompt, aspect_ratio='1:1')
    TMP.mkdir(parents=True, exist_ok=True)
    path = TMP / f"frame-{datetime.now(TZ).strftime('%H%M%S')}.png"
    img.save(path, format='PNG', optimize=True)
    import sys
    sys.path.insert(0, str(config.BASE_DIR / 'scripts'))
    from telegram_watch_tower import send_photo  # noqa: WPS433
    ok = send_photo(token, chat, path, caption='')
    path.unlink(missing_ok=True)
    if ok:
        LAST_SEND.write_text(
            json.dumps({'ts': datetime.now(TZ).isoformat(), 'ok': True, 'chars': len(prompt)}),
            encoding='utf-8',
        )
    return ok


# Back-compat alias used by router /new rescue
def send_simple_frame(_line1: str, _line2: str, prompt: str) -> bool:
    return send_image_bytes_prompt(prompt)


@function_tool
def craft_punchline_prompt(prompt: str) -> str:
    """Validate DIRECTOR's full image prompt before render.
    prompt MUST be >= MIN_PROMPT_CHARS (default 800) and describe a 2D graphic punchline poster:
    bright solid bg + grid, matte black central silhouette/concept, bold sans typography IN the art
    (not UI cards), premium vector marketing look. Include punchline words + any STAGEHAND facts
    as designed typography. Returns JSON {ok, chars, prompt} or error."""
    try:
        p = assert_prompt_length(prompt)
    except ValueError as e:
        return json.dumps({
            'ok': False,
            'error': str(e),
            'min_chars': MIN_PROMPT_CHARS,
            'got': len((prompt or '').strip()),
        })
    return json.dumps({'ok': True, 'chars': len(p), 'prompt': p, 'min_chars': MIN_PROMPT_CHARS})


@function_tool
def lens_render_and_courier_send(prompt: str) -> str:
    """LENS + COURIER: Render the FULL prompt with Grok Imagine and send Telegram photo.
    Typography must already be inside the prompt — we do NOT overlay white text cards.
    Call craft_punchline_prompt first if unsure about length."""
    try:
        ok = send_image_bytes_prompt(prompt)
    except ValueError as e:
        return json.dumps({'ok': False, 'error': str(e), 'min_chars': MIN_PROMPT_CHARS})
    return json.dumps({'ok': ok, 'delivered': 'telegram_photo' if ok else 'failed'})
