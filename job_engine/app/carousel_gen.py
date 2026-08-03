"""TECH JOB MARKET MOVEMENT — carousel slide generator (Replicate + Pillow).

Pulls live Ultron facts, paints fiery 1080×1350 slides, writes ephemeral
PNGs under job_engine/.data/carousel_tmp/ for Telegram upload only.
"""

from __future__ import annotations

import json
import shutil
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from app import config

BASE = 'http://127.0.0.1:8001'
TZ = ZoneInfo('Asia/Kolkata')
W, H = 1080, 1350
TMP_ROOT = config.BASE_DIR / '.data' / 'carousel_tmp'

# VIGIL-adjacent fire palette (dark stage + orange/cyan)
ORANGE = (255, 85, 0)
AMBER = (255, 170, 0)
CYAN = (80, 220, 255)
WHITE = (255, 255, 255)
MUTED = (200, 200, 210)


@dataclass
class Slide:
    key: str
    headline: str
    sub: str
    stat: str
    bg_prompt: str


def _get(path: str, params: dict | None = None) -> dict:
    url = BASE + path
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))


def fetch_facts() -> dict:
    tower = _get('/api/ultron/tower')
    sig24 = _get('/api/ultron/signals', {'days': 0})
    sig7 = _get('/api/ultron/signals', {'days': 7})
    stats = tower.get('stats') or {}
    s24 = sig24.get('signals') or {}
    s7 = sig7.get('signals') or {}
    top = (tower.get('top_companies') or [])[:3]
    roles = (tower.get('per_role') or [])[:3]
    growing = (s24.get('growing_roles') or s7.get('growing_roles') or [])[:3]

    rise = growing[0] if growing else (roles[0] if roles else {})
    rise_name = rise.get('name') or 'AI Engineer'
    if rise.get('delta') is not None:
        rise_delta = int(rise['delta'])
    elif rise.get('recent') is not None and rise.get('prior') is not None:
        rise_delta = int(rise['recent']) - int(rise['prior'])
    else:
        rise_delta = int(rise.get('n') or 0)

    company = top[0] if top else {}
    return {
        'total_jobs': int(stats.get('total_jobs') or 0),
        'jobs_today': int(stats.get('jobs_today') or 0),
        'companies': int(stats.get('companies') or 0),
        'headline24': (s24.get('headline') or '').strip(),
        'headline7': (s7.get('headline') or '').strip(),
        'rise_name': rise_name,
        'rise_delta': rise_delta,
        'company_name': company.get('name') or 'Top hirers',
        'company_n': int(company.get('n') or 0),
        'roles': roles,
        'top': top,
        'now': datetime.now(TZ),
    }


def build_slides(facts: dict) -> list[Slide]:
    style = (
        'cinematic dark cyberpunk campus, orange and cyan neon rim light, '
        'deep black background, high contrast, no text, no letters, no watermark, '
        'vertical 3:4 composition, powerful hopeful energy for tech graduates'
    )
    today = facts['jobs_today']
    total = facts['total_jobs']
    rise = facts['rise_name']
    delta = facts['rise_delta']
    co = facts['company_name']
    co_n = facts['company_n']

    return [
        Slide(
            key='hook',
            headline='Do I still have hope\nin the TECH job market?',
            sub='TECH JOB MARKET MOVEMENT',
            stat='Facts from the live tower — not fear.',
            bg_prompt=f'{style}, sunrise over neon city skyline, silhouette of young graduate looking up',
        ),
        Slide(
            key='pulse',
            headline='Live TECH openings',
            sub='Caught by Watch Tower · fresher lens',
            stat=f'{today:,} today\n{total:,} in the signal window',
            bg_prompt=f'{style}, cascading data streams forming a tower of light',
        ),
        Slide(
            key='rising',
            headline='Rising role',
            sub='Where energy is moving right now',
            stat=f'{rise}\n+{delta} momentum',
            bg_prompt=f'{style}, ascending glass tower with orange fire at the tip',
        ),
        Slide(
            key='hirer',
            headline='Hiring pulse',
            sub='Companies opening doors',
            stat=f'{co}\n{co_n} openings in window',
            bg_prompt=f'{style}, corporate glass towers with warm window lights at night',
        ),
        Slide(
            key='fresher',
            headline='Built for freshers',
            sub='Track A · Internship + Entry signals',
            stat=f'{facts["companies"]:,} companies\nin the TECH net',
            bg_prompt=f'{style}, campus of ice-blue glass towers, students walking toward light',
        ),
        Slide(
            key='cta',
            headline='Facts, not fear.',
            sub='JobMaster.agency · VIGIL · Quanta HR',
            stat='Open Telegram · ask the tower\n/carousel anytime',
            bg_prompt=f'{style}, orange ember core glowing in a dark hall, hopeful close',
        ),
    ]


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split('\n'):
        words = paragraph.split()
        if not words:
            lines.append('')
            continue
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


def _generate_bg(prompt: str) -> Image.Image:
    import replicate

    token = config.REPLICATE_API_TOKEN
    if not token:
        raise RuntimeError('REPLICATE_API_TOKEN missing in job_engine/.env')

    client = replicate.Client(api_token=token)
    output = client.run(
        config.REPLICATE_MODEL,
        input={
            'prompt': prompt,
            'aspect_ratio': '3:4',
            'output_format': 'png',
            'output_quality': 90,
            'num_outputs': 1,
            'go_fast': True,
        },
    )
    # FileOutput list or single
    item = output[0] if isinstance(output, list) else output
    if hasattr(item, 'read'):
        data = item.read()
    else:
        url = str(item)
        with urllib.request.urlopen(url, timeout=120) as resp:
            data = resp.read()
    from io import BytesIO
    img = Image.open(BytesIO(data)).convert('RGB')
    if img.size != (W, H):
        img = img.resize((W, H), Image.Resampling.LANCZOS)
    return img


def _compose(bg: Image.Image, slide: Slide) -> Image.Image:
    img = bg.copy()
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    # Bottom-heavy scrim for text
    for y in range(H // 3, H):
        a = int(40 + 180 * ((y - H / 3) / (H * 2 / 3)))
        od.line([(0, y), (W, y)], fill=(5, 3, 2, min(220, a)))
    # Top brand bar glow
    od.rectangle([(0, 0), (W, 90)], fill=(5, 3, 2, 160))
    img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
    draw = ImageDraw.Draw(img)

    brand_f = _font(28, bold=True)
    head_f = _font(64, bold=True)
    sub_f = _font(34, bold=False)
    stat_f = _font(56, bold=True)
    foot_f = _font(24, bold=False)

    draw.text((48, 32), 'TECH JOB MARKET MOVEMENT', font=brand_f, fill=ORANGE)

    y = 220
    for line in _wrap(draw, slide.headline, head_f, W - 96):
        draw.text((48, y), line, font=head_f, fill=WHITE)
        y += 74

    y += 16
    for line in _wrap(draw, slide.sub, sub_f, W - 96):
        draw.text((48, y), line, font=sub_f, fill=CYAN)
        y += 44

    y = max(y + 40, 720)
    # Accent bar
    draw.rectangle([(48, y), (220, y + 8)], fill=ORANGE)
    y += 36
    for line in _wrap(draw, slide.stat, stat_f, W - 96):
        draw.text((48, y), line, font=stat_f, fill=AMBER)
        y += 68

    draw.text((48, H - 64), 'JobMaster.agency · VIGIL · Quanta HR', font=foot_f, fill=MUTED)
    return img


def build_caption(facts: dict) -> str:
    now = facts['now'].strftime('%Y-%m-%d %H:%M IST')
    lines = [
        'TECH JOB MARKET MOVEMENT',
        'Do I still have hope in the TECH job market?',
        '',
        f'Live · {facts["jobs_today"]:,} openings today · {facts["total_jobs"]:,} in window',
        f'Rising · {facts["rise_name"]} (+{facts["rise_delta"]})',
        f'Hiring pulse · {facts["company_name"]} ({facts["company_n"]})',
        '',
        'by JobMaster.agency · power of VIGIL · AI · Quanta HR',
        f'Tower facts · {now}',
        'Reply /carousel for a fresh set',
    ]
    if facts.get('headline24'):
        lines.insert(3, facts['headline24'][:180])
    return '\n'.join(lines)


def generate_carousel(*, clean: bool = True) -> tuple[list[Path], str, Path]:
    """Return (slide_paths, caption, run_dir). Caller sends then may delete run_dir."""
    facts = fetch_facts()
    slides = build_slides(facts)
    caption = build_caption(facts)

    run_dir = TMP_ROOT / datetime.now(TZ).strftime('%Y%m%d-%H%M%S')
    if clean and TMP_ROOT.exists():
        # Keep only last 2 runs max — ephemeral
        for old in sorted(TMP_ROOT.iterdir(), reverse=True)[1:]:
            if old.is_dir():
                shutil.rmtree(old, ignore_errors=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for i, slide in enumerate(slides, start=1):
        bg = _generate_bg(slide.bg_prompt)
        composed = _compose(bg, slide)
        out = run_dir / f'slide-{i:02d}-{slide.key}.png'
        composed.save(out, format='PNG', optimize=True)
        paths.append(out)

    (run_dir / 'caption.txt').write_text(caption, encoding='utf-8')
    return paths, caption, run_dir
