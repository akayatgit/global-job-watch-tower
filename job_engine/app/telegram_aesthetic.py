"""Calm bright-white aesthetic Telegram replies via Grok Imagine (not memes)."""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from app import config
from app.prompt_dictionary import scene_for_chat

BASE = 'http://127.0.0.1:8001'
TZ = ZoneInfo('Asia/Kolkata')
W, H = 1080, 1080
TMP = config.BASE_DIR / '.data' / 'aesthetic_tmp'


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
    for para in text.split('\n'):
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


def _tower_facts() -> dict:
    out = {'line': None, 'today': 0, 'total': 0}
    try:
        req = urllib.request.Request(BASE + '/api/ultron/tower', headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=12) as resp:
            d = json.loads(resp.read().decode())
        stats = d.get('stats') or {}
        out['today'] = int(stats.get('jobs_today') or 0)
        out['total'] = int(stats.get('total_jobs') or 0)
        if out['today'] or out['total']:
            out['line'] = f"{out['today']} openings today · {out['total']} in window"
    except Exception:
        pass
    return out


def helpful_response(user_msg: str) -> tuple[str, str, str]:
    """Calm helpful copy that would have been Hermes' reply — rendered into the image."""
    msg = (user_msg or '').strip()
    low = msg.lower()
    facts = _tower_facts()
    fact = facts['line']

    if any(w in low for w in ('hi', 'hello', 'hey', 'vanakkam', 'hai')):
        title = 'Hello — Vigil is here'
        body = 'Ask about hope, a role, a city, or say Carousel for a full briefing.'
    elif any(w in low for w in ('hope', 'scared', 'fear', 'future', 'jobless')):
        title = 'There is still a path'
        body = fact or 'The tower is watching live TECH openings for you.'
    elif any(w in low for w in ('bangalore', 'bengaluru', 'chennai', 'hyderabad', 'city')):
        title = 'Your city is in the signal'
        body = fact or 'Ask Carousel + role + city for a dated company list.'
    elif any(w in low for w in ('data', 'analyst', 'engineer', 'devops', 'ai', 'role', 'job')):
        title = 'Let’s read the market calmly'
        body = fact or 'Say Carousel with the role and city for a structured album.'
    elif 'thank' in low or 'love' in low:
        title = 'Glad you’re here'
        body = 'Whenever you’re ready — hope, facts, Carousel.'
    else:
        snippet = re.sub(r'\s+', ' ', msg)[:70]
        title = 'I’m listening'
        body = f'About: {snippet}' if snippet else (fact or 'Share a role, city, or say Carousel.')

    return title, body, fact or ''


def compose_aesthetic_reply(user_msg: str) -> Path:
    title, body, fact = helpful_response(user_msg)
    overlay = title
    prompt = scene_for_chat(user_msg, helpful_line=title, fact_line=fact or None)

    from app.replicate_img import generate_image
    bg = generate_image(prompt, aspect_ratio='1:1')
    if bg.size != (W, H):
        bg = bg.resize((W, H), Image.Resampling.LANCZOS)

    # Soft bright panel for readable calm text (facts must be accurate — Pillow)
    overlay_img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay_img)
    od.rounded_rectangle([(48, H - 320), (W - 48, H - 48)], radius=28, fill=(255, 255, 255, 210))
    img = Image.alpha_composite(bg.convert('RGBA'), overlay_img).convert('RGB')
    draw = ImageDraw.Draw(img)

    title_f = _font(40, True)
    body_f = _font(28, False)
    foot_f = _font(20, False)
    ink = (40, 44, 52)
    mute = (90, 96, 110)

    y = H - 290
    for line in _wrap(draw, title, title_f, W - 140):
        draw.text((72, y), line, font=title_f, fill=ink)
        y += 48
    y += 8
    for line in _wrap(draw, body, body_f, W - 140):
        draw.text((72, y), line, font=body_f, fill=mute)
        y += 36

    draw.text((72, H - 78), 'JobMaster · Vigil · Quanta HR · Grok Imagine', font=foot_f, fill=(140, 144, 155))

    TMP.mkdir(parents=True, exist_ok=True)
    for old in sorted(TMP.glob('*.png'))[:-4]:
        old.unlink(missing_ok=True)
    out = TMP / f"reply-{datetime.now(TZ).strftime('%H%M%S')}.png"
    img.save(out, format='PNG', optimize=True)
    return out


# Back-compat alias
compose_meme = compose_aesthetic_reply
