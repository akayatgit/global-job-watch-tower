"""TECH JOB MARKET MOVEMENT — carousel slide generator (Replicate + Pillow).

Pulls live Ultron facts, paints fiery 1080×1350 slides, writes ephemeral
PNGs under job_engine/.data/carousel_tmp/ for Telegram upload only.
"""

from __future__ import annotations

import json
import re
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

# Bright-white calm palette (Ashok 2026-08-03 — aesthetic, not meme/cyber)
INK = (36, 40, 48)
MUTED = (90, 96, 110)
ACCENT = (40, 110, 180)
WHITE = (255, 255, 255)
PANEL = (255, 255, 255, 200)


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
    from app.prompt_dictionary import scene_for_carousel_slide

    today = facts['jobs_today']
    total = facts['total_jobs']
    rise = facts['rise_name']
    delta = facts['rise_delta']
    co = facts['company_name']
    co_n = facts['company_n']

    specs = [
        ('hook', 'Do I still have hope\nin the TECH job market?', 'TECH JOB MARKET MOVEMENT',
         'Facts from the live tower — not fear.'),
        ('pulse', 'Live TECH openings', 'Caught by Watch Tower · fresher lens',
         f'{today:,} today\n{total:,} in the signal window'),
        ('rising', 'Rising role', 'Where energy is moving right now',
         f'{rise}\n+{delta} momentum'),
        ('hirer', 'Hiring pulse', 'Companies opening doors',
         f'{co}\n{co_n} openings in window'),
        ('fresher', 'Built for freshers', 'Track A · Internship + Entry signals',
         f'{facts["companies"]:,} companies\nin the TECH net'),
        ('cta', 'Facts, not fear.', 'JobMaster.agency · VIGIL · Quanta HR',
         'Ask Vigil anytime\nSay Carousel for a fresh set'),
    ]
    return [
        Slide(
            key=k,
            headline=h,
            sub=s,
            stat=st,
            bg_prompt=scene_for_carousel_slide(slide_key=k, headline=h.replace('\n', ' ')),
        )
        for k, h, s, st in specs
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
    from app.replicate_img import generate_image

    img = generate_image(prompt, aspect_ratio='3:4')
    if img.size != (W, H):
        img = img.resize((W, H), Image.Resampling.LANCZOS)
    return img


def _compose(bg: Image.Image, slide: Slide) -> Image.Image:
    img = bg.copy()
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle([(36, 36), (W - 36, 120)], radius=20, fill=PANEL)
    od.rounded_rectangle([(36, H - 520), (W - 36, H - 36)], radius=28, fill=PANEL)
    img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
    draw = ImageDraw.Draw(img)

    brand_f = _font(26, bold=True)
    head_f = _font(52, bold=True)
    sub_f = _font(30, bold=False)
    stat_f = _font(44, bold=True)
    foot_f = _font(22, bold=False)

    draw.text((56, 58), 'TECH JOB MARKET MOVEMENT', font=brand_f, fill=ACCENT)

    y = H - 480
    for line in _wrap(draw, slide.headline, head_f, W - 120):
        draw.text((56, y), line, font=head_f, fill=INK)
        y += 58

    y += 8
    for line in _wrap(draw, slide.sub, sub_f, W - 120):
        draw.text((56, y), line, font=sub_f, fill=MUTED)
        y += 38

    y += 16
    draw.rectangle([(56, y), (200, y + 6)], fill=ACCENT)
    y += 24
    for line in _wrap(draw, slide.stat, stat_f, W - 120):
        draw.text((56, y), line, font=stat_f, fill=INK)
        y += 52

    draw.text((56, H - 72), 'JobMaster.agency · VIGIL · Quanta HR · Grok Imagine', font=foot_f, fill=MUTED)
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
        'Say Carousel + role + city for a focused set',
    ]
    if facts.get('headline24'):
        lines.insert(3, facts['headline24'][:180])
    return '\n'.join(lines)


_CITY_ALIASES = {
    'bangalore': 'bengaluru',
    'bengaluru': 'bengaluru',
    'blr': 'bengaluru',
    'chennai': 'chennai',
    'madras': 'chennai',
    'hyderabad': 'hyderabad',
    'hyd': 'hyderabad',
    'pune': 'pune',
    'mumbai': 'mumbai',
    'delhi': 'delhi',
    'gurugram': 'gurugram',
    'gurgaon': 'gurugram',
    'noida': 'noida',
    'kerala': 'kerala',
    'kochi': 'kerala',
    'remote': 'remote',
}


def parse_topic(msg: str) -> dict:
    """Best-effort role + city from a Carousel request."""
    text = (msg or '').strip()
    low = text.lower()
    city = None
    city_label = None
    for alias, key in _CITY_ALIASES.items():
        if re.search(rf'\b{re.escape(alias)}\b', low):
            city = key
            city_label = alias.title() if alias != 'blr' else 'Bengaluru'
            if key == 'bengaluru':
                city_label = 'Bengaluru'
            break

    role = None
    m = re.search(
        r'carousel\s+(?:of|for|on)?\s*(.+?)(?:\s+for\s+today|\s+in\s+|\s+with\s+|$)',
        low, re.I,
    )
    if m:
        role = m.group(1).strip(' .')
    if not role:
        m2 = re.search(r'\b(?:of|for)\s+([a-z0-9 /+&-]{3,40})\s+(?:in|at|for)\b', low)
        if m2:
            role = m2.group(1).strip()
    if role:
        for alias in _CITY_ALIASES:
            role = re.sub(rf'\b{re.escape(alias)}\b', '', role, flags=re.I).strip()
        role = re.sub(r'\b(today|date|list|companies|openings|jobs)\b', '', role, flags=re.I)
        role = re.sub(r'\s+', ' ', role).strip(' -')
    if not role or len(role) < 3:
        role = 'Data Analyst' if 'analyst' in low else None

    return {'role': role, 'city': city, 'city_label': city_label or (city or '').title()}


def fetch_topic_jobs(role: str | None, city: str | None, *, limit: int = 40) -> list[dict]:
    params: dict = {'limit': limit}
    if role:
        params['title'] = role
    if city:
        params['city'] = city
    data = _get('/api/jobs', params)
    if not isinstance(data, list):
        return []
    return data


def build_topic_slides(role: str, city_label: str, jobs: list[dict], now: datetime) -> tuple[list[Slide], str]:
    from app.prompt_dictionary import scene_for_carousel_slide

    date_s = now.strftime('%d %b %Y')
    counts: dict[str, int] = {}
    for j in jobs:
        name = (j.get('company_name') or j.get('company') or 'Unknown').strip()
        counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    top_lines = [f'{n} — {c}' for n, c in ranked[:6]]
    more_lines = [f'{n} — {c}' for n, c in ranked[6:12]]
    if not top_lines:
        top_lines = ['No matching openings in tower yet']

    raw = [
        ('topic-hook', f'{role}\n{city_label or "India"}', 'TECH JOB MARKET MOVEMENT · Carousel',
         f'{len(jobs)} openings\nin tower match'),
        ('date', 'Live snapshot', f'Date · {date_s} IST', 'Tower facts only\nNo invented markets'),
        ('companies', 'Companies hiring', f'{role} · {city_label or "All cities"}', '\n'.join(top_lines[:5])),
        ('more', 'More of the list', 'Ranked by openings in match',
         '\n'.join(more_lines[:5]) if more_lines else '— full list is short today —'),
        ('pulse', 'What to know', 'Fresher-friendly TECH lens',
         f'Top hirer\n{ranked[0][0] if ranked else "—"}'),
        ('cta', 'Facts, not fear.', 'JobMaster.agency · VIGIL · Quanta HR',
         'Say Carousel + role + city\nfor the next pulse'),
    ]
    slides = [
        Slide(
            key=k,
            headline=h,
            sub=s,
            stat=st,
            bg_prompt=scene_for_carousel_slide(
                slide_key=k, headline=h.replace('\n', ' '), role_hint=role,
            ),
        )
        for k, h, s, st in raw
    ]
    caption = '\n'.join([
        'TECH JOB MARKET MOVEMENT · Carousel',
        f'{role} · {city_label or "India"} · {date_s}',
        f'{len(jobs)} openings matched in tower',
        f'Top: {ranked[0][0]} ({ranked[0][1]})' if ranked else 'No matches yet',
        '',
        'by JobMaster.agency · VIGIL · Quanta HR',
        'Tower facts only',
    ])
    return slides, caption


def generate_carousel(
    *,
    clean: bool = True,
    topic_msg: str | None = None,
) -> tuple[list[Path], str, Path]:
    """Return (slide_paths, caption, run_dir). Caller sends then may delete run_dir."""
    now = datetime.now(TZ)
    topic = parse_topic(topic_msg or '') if topic_msg else {}
    if topic.get('role'):
        jobs = fetch_topic_jobs(topic.get('role'), topic.get('city'))
        slides, caption = build_topic_slides(
            topic['role'].title(),
            topic.get('city_label') or '',
            jobs,
            now,
        )
    else:
        facts = fetch_facts()
        slides = build_slides(facts)
        caption = build_caption(facts)

    run_dir = TMP_ROOT / datetime.now(TZ).strftime('%Y%m%d-%H%M%S')
    if clean and TMP_ROOT.exists():
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
