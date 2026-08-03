"""Goofy Tanglish meme frames for Telegram image-only chat (Replicate + Pillow)."""

from __future__ import annotations

import json
import re
import shutil
import urllib.parse
import urllib.request
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from app import config

BASE = 'http://127.0.0.1:8001'
TZ = ZoneInfo('Asia/Kolkata')
W, H = 1080, 1080
TMP = config.BASE_DIR / '.data' / 'meme_tmp'


def _font(size: int, bold: bool = True):
    paths = [
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


def _tower_one_liner() -> str | None:
    try:
        url = BASE + '/api/ultron/tower'
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=12) as resp:
            d = json.loads(resp.read().decode())
        stats = d.get('stats') or {}
        today = int(stats.get('jobs_today') or 0)
        total = int(stats.get('total_jobs') or 0)
        if today or total:
            return f'Tower truth: {today} today · {total} in window'
    except Exception:
        return None
    return None


def punchlines(user_msg: str) -> tuple[str, str, str]:
    """Return (top, bottom, bg_prompt) — Tanglish goofy."""
    msg = (user_msg or '').strip()
    low = msg.lower()
    fact = _tower_one_liner()

    if any(w in low for w in ('hope', 'scared', 'fear', 'future', 'jobless')):
        top = 'Hope iruka da??'
        bottom = fact or 'Tower solludhu — still fighting!'
        bg = 'funny tamil cinema style underdog hero looking at neon city, warm comic energy, no text'
    elif any(w in low for w in ('bangalore', 'bengaluru', 'chennai', 'hyderabad', 'city')):
        top = 'City-ku scene enna da?'
        bottom = fact or 'Metro openings dance aadudhu'
        bg = 'comic neon india tech city with funny surprised graduate, meme energy, no text'
    elif any(w in low for w in ('data', 'analyst', 'engineer', 'devops', 'ai ', 'role')):
        top = 'Role hunting mode ON 🔥'
        bottom = (fact or 'Fact check pannu — invent pannaathinga')[:80]
        bg = 'goofy cyberpunk desk with laptop and chai, orange neon, meme comic, no text'
    elif any(w in low for w in ('hi', 'hello', 'hey', 'vanakkam', 'hai')):
        top = 'Vanakkam da boss!'
        bottom = 'VIGIL online — image mode only 😎'
        bg = 'funny robot waving with orange cape, dark stage, comic meme, no text'
    elif 'thank' in low or 'love' in low:
        top = 'Love you too da 🧡'
        bottom = 'Job movement continue aagum!'
        bg = 'warm comic heart made of circuit boards, orange glow, meme, no text'
    else:
        # Short echo of user intent
        snippet = re.sub(r'\s+', ' ', msg)[:48] or 'Enna scene?'
        top = f'{snippet}…'
        bottom = fact or 'Image-la pesuvom — text spam illa!'
        bg = 'chaotic funny tamil meme energy neon tower, orange cyan, comic panel, no text'

    return top, bottom, bg


def _replicate_bg(prompt: str) -> Image.Image:
    import replicate

    token = config.REPLICATE_API_TOKEN
    if not token:
        raise RuntimeError('REPLICATE_API_TOKEN missing')
    client = replicate.Client(api_token=token)
    model = config.REPLICATE_MODEL
    out = client.run(
        model,
        input={
            'prompt': prompt,
            'aspect_ratio': '1:1',
            'output_format': 'png',
            'num_outputs': 1,
            'go_fast': True,
        },
    )
    item = out[0] if isinstance(out, list) else out
    data = item.read() if hasattr(item, 'read') else urllib.request.urlopen(str(item), timeout=120).read()
    img = Image.open(BytesIO(data)).convert('RGB')
    if img.size != (W, H):
        img = img.resize((W, H), Image.Resampling.LANCZOS)
    return img


def compose_meme(user_msg: str) -> Path:
    top, bottom, bg_prompt = punchlines(user_msg)
    bg = _replicate_bg(bg_prompt)
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([(0, 0), (W, 160)], fill=(0, 0, 0, 170))
    od.rectangle([(0, H - 200), (W, H)], fill=(0, 0, 0, 190))
    img = Image.alpha_composite(bg.convert('RGBA'), overlay).convert('RGB')
    draw = ImageDraw.Draw(img)
    top_f = _font(52, True)
    bot_f = _font(40, True)
    brand_f = _font(22, False)

    y = 28
    for line in _wrap(draw, top, top_f, W - 80):
        # outline
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            draw.text((40 + dx, y + dy), line, font=top_f, fill=(0, 0, 0))
        draw.text((40, y), line, font=top_f, fill=(255, 220, 80))
        y += 58

    y = H - 170
    for line in _wrap(draw, bottom, bot_f, W - 80):
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            draw.text((40 + dx, y + dy), line, font=bot_f, fill=(0, 0, 0))
        draw.text((40, y), line, font=bot_f, fill=(255, 255, 255))
        y += 48

    draw.text((40, H - 36), 'VIGIL · Tanglish mode · JobMaster', font=brand_f, fill=(180, 180, 190))

    TMP.mkdir(parents=True, exist_ok=True)
    # keep only last few
    for old in sorted(TMP.glob('*.png'))[:-3]:
        old.unlink(missing_ok=True)
    out = TMP / f"meme-{datetime.now(TZ).strftime('%H%M%S')}.png"
    img.save(out, format='PNG', optimize=True)
    return out
