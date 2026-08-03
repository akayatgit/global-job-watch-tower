"""LENS + COURIER tools — craft skit frames, Grok Imagine, Telegram send."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agents import function_tool
from PIL import Image, ImageDraw, ImageFont

from app import config
from app.prompt_dictionary import fill_cinematic
from app.replicate_img import generate_image

TZ = ZoneInfo('Asia/Kolkata')
TMP = config.BASE_DIR / '.data' / 'director_frames'
LAST_SEND = TMP / 'last_send.json'
W, H = 1080, 1080


def _font(size: int, bold: bool = True):
    paths = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf' if bold
        else '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold
        else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]
    for p in paths:
        if Path(p).exists():
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in (text or '').split('\n'):
        words = para.split() or ['']
        cur = words[0]
        for w in words[1:]:
            trial = f'{cur} {w}'
            if draw.textlength(trial, font=font) <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


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


@function_tool
def craft_skit_frame(
    setting: str,
    environment: str,
    subjects: str,
    action: str,
    line1: str,
    line2: str = '',
    lighting: str = (
        'Soft bright daylight, Pinterest 2026 editorial comics lighting, '
        'high-key whites with warm Tamil Nadu sun accents'
    ),
) -> str:
    """LENS prep: Build one Tamil Nadu Pinterest-2026 comic skit prompt with LIMITED on-image text.
    line1/line2 = short readable lines (max ~8 words each). Use STAGEHAND facts in those lines — never invent counts.
    Returns JSON {prompt, line1, line2}."""
    limited = line1.strip()
    if line2.strip():
        limited = f'{limited} · {line2.strip()}'
    prompt = fill_cinematic(
        setting=setting,
        environment=environment,
        lighting=lighting,
        subjects=subjects,
        action=action,
        overlay_text=limited[:100],
        template_key='tn_pinterest_comic_2026',
        include_overlay=True,
    )
    return json.dumps({'prompt': prompt, 'line1': line1.strip(), 'line2': line2.strip()})


def send_simple_frame(line1: str, line2: str, prompt: str) -> bool:
    """Non-tool helper for /new and fallbacks."""
    env = _hermes_env()
    token = env.get('TELEGRAM_BOT_TOKEN')
    chat = env.get('TELEGRAM_HOME_CHANNEL')
    if not token or not chat:
        return False
    img = generate_image(prompt, aspect_ratio='1:1')
    if img.size != (W, H):
        img = img.resize((W, H), Image.Resampling.LANCZOS)
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle([(40, H - 280), (W - 40, H - 40)], radius=32, fill=(255, 255, 255, 220))
    composed = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
    draw = ImageDraw.Draw(composed)
    title_f = _font(36, True)
    body_f = _font(26, False)
    foot_f = _font(18, False)
    y = H - 250
    for line in _wrap(draw, line1, title_f, W - 120)[:3]:
        draw.text((64, y), line, font=title_f, fill=(28, 32, 40))
        y += 42
    if line2:
        for line in _wrap(draw, line2, body_f, W - 120)[:3]:
            draw.text((64, y), line, font=body_f, fill=(80, 86, 100))
            y += 34
    draw.text((64, H - 70), 'JobMaster · DIRECTOR · Vigil · Grok Imagine', font=foot_f, fill=(150, 154, 165))
    TMP.mkdir(parents=True, exist_ok=True)
    path = TMP / f"frame-{datetime.now(TZ).strftime('%H%M%S')}.png"
    composed.save(path, format='PNG', optimize=True)
    import sys
    sys.path.insert(0, str(config.BASE_DIR / 'scripts'))
    from telegram_watch_tower import send_photo  # noqa: WPS433
    ok = send_photo(token, chat, path, caption='')
    path.unlink(missing_ok=True)
    if ok:
        TMP.mkdir(parents=True, exist_ok=True)
        LAST_SEND.write_text(
            json.dumps({'ts': datetime.now(TZ).isoformat(), 'ok': True}),
            encoding='utf-8',
        )
    return ok


@function_tool
def lens_render_and_courier_send(
    prompt: str,
    line1: str,
    line2: str = '',
) -> str:
    """LENS + COURIER: Render with Grok Imagine, burn limited text panel, send Telegram photo (no caption essay).
    Call after craft_skit_frame (or with a full cinematic prompt)."""
    ok = send_simple_frame(line1 or 'Vigil', line2 or '', prompt)
    return json.dumps({'ok': ok, 'delivered': 'telegram_photo' if ok else 'failed'})
