"""Draw fact boards / charts from exact numbers (Pillow) — never freehand by Grok."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W = H = 1080
BG = (10, 14, 24)
PANEL = (18, 24, 38)
INK = (240, 244, 250)
MUTED = (150, 162, 180)
ACCENT = (255, 120, 40)
CYAN = (80, 200, 255)
SLICE_COLORS = [
    (64, 140, 255),
    (255, 140, 60),
    (80, 200, 140),
    (180, 110, 255),
    (255, 90, 120),
    (255, 210, 70),
    (90, 220, 220),
    (200, 200, 210),
]


def _font(size: int, bold: bool = True) -> ImageFont.ImageFont:
    candidates = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold
        else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf' if bold
        else '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    words = (text or '').split()
    if not words:
        return ['']
    lines: list[str] = []
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


def render_kpi_board(
    *,
    title: str,
    hero: str,
    hero_label: str,
    lines: list[str] | None = None,
    footer: str = '',
) -> Image.Image:
    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(48, 48), (W - 48, H - 48)], radius=36, fill=PANEL)
    title_f = _font(36, True)
    hero_f = _font(96, True)
    label_f = _font(34, False)
    line_f = _font(30, False)
    foot_f = _font(24, False)

    draw.text((80, 90), title[:48], font=title_f, fill=ACCENT)
    draw.text((80, 220), str(hero)[:18], font=hero_f, fill=INK)
    draw.text((80, 340), hero_label[:56], font=label_f, fill=MUTED)

    y = 430
    for raw in (lines or [])[:8]:
        for ln in _wrap(draw, str(raw), line_f, W - 180):
            draw.text((80, y), ln, font=line_f, fill=INK)
            y += 42
        y += 10

    if footer:
        draw.text((80, H - 110), footer[:70], font=foot_f, fill=MUTED)
    return img


def render_pie_board(
    *,
    title: str,
    slices: list[tuple[str, int]],
    subtitle: str = '',
    footer: str = '',
) -> Image.Image:
    """Pie + legend from exact (label, value) pairs — values are source of truth."""
    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(40, 40), (W - 40, H - 40)], radius=32, fill=PANEL)

    title_f = _font(34, True)
    sub_f = _font(26, False)
    leg_f = _font(28, True)
    val_f = _font(28, False)
    foot_f = _font(22, False)

    draw.text((70, 70), title[:52], font=title_f, fill=ACCENT)
    if subtitle:
        draw.text((70, 120), subtitle[:64], font=sub_f, fill=MUTED)

    clean = [(str(n), max(0, int(v))) for n, v in slices if str(n).strip()]
    clean = [(n, v) for n, v in clean if v > 0][:8]
    total = sum(v for _, v in clean) or 1

    cx, cy, r = 340, 520, 220
    bbox = [cx - r, cy - r, cx + r, cy + r]
    start = -90.0
    for i, (name, val) in enumerate(clean):
        extent = 360.0 * (val / total)
        color = SLICE_COLORS[i % len(SLICE_COLORS)]
        if extent <= 0:
            continue
        # Pillow pieslice uses degrees
        draw.pieslice(bbox, start=start, end=start + extent, fill=color)
        start += extent
    # center hole for donut readability
    hole = 90
    draw.ellipse([cx - hole, cy - hole, cx + hole, cy + hole], fill=PANEL)
    draw.text((cx - 40, cy - 24), str(total), font=_font(40, True), fill=INK)

    # Legend (exact numbers)
    lx, ly = 620, 280
    for i, (name, val) in enumerate(clean):
        color = SLICE_COLORS[i % len(SLICE_COLORS)]
        draw.rounded_rectangle([(lx, ly + 6), (lx + 28, ly + 34)], radius=6, fill=color)
        label = f'{name[:28]}'
        draw.text((lx + 44, ly), label, font=leg_f, fill=INK)
        draw.text((lx + 44, ly + 36), f'{val}', font=val_f, fill=CYAN)
        ly += 84

    if footer:
        draw.text((70, H - 90), footer[:72], font=foot_f, fill=MUTED)
    return img


def render_list_board(
    *,
    title: str,
    rows: list[dict],
    subtitle: str = '',
    footer: str = '',
) -> Image.Image:
    """Text stat board — title/company lines from exact rows."""
    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(40, 40), (W - 40, H - 40)], radius=32, fill=PANEL)

    title_f = _font(34, True)
    sub_f = _font(26, False)
    row_f = _font(28, True)
    co_f = _font(24, False)
    foot_f = _font(22, False)
    num_f = _font(26, True)

    draw.text((70, 70), title[:52], font=title_f, fill=ACCENT)
    if subtitle:
        draw.text((70, 118), subtitle[:64], font=sub_f, fill=MUTED)

    y = 190
    for i, row in enumerate((rows or [])[:8], start=1):
        title_s = str(row.get('title') or row.get('name') or '—')[:48]
        co = str(row.get('company') or '')[:40]
        meta = str(row.get('meta') or row.get('posted_date') or '')[:28]
        draw.text((70, y), f'{i:02d}', font=num_f, fill=CYAN)
        for ln in _wrap(draw, title_s, row_f, W - 220):
            draw.text((140, y), ln, font=row_f, fill=INK)
            y += 34
        detail = ' · '.join(x for x in (co, meta) if x)
        if detail:
            draw.text((140, y), detail[:56], font=co_f, fill=MUTED)
            y += 30
        y += 22
        if y > H - 140:
            break

    if footer:
        draw.text((70, H - 90), footer[:72], font=foot_f, fill=MUTED)
    return img


def render_bar_board(
    *,
    title: str,
    bars: list[tuple[str, int]],
    subtitle: str = '',
    footer: str = '',
) -> Image.Image:
    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(40, 40), (W - 40, H - 40)], radius=32, fill=PANEL)
    draw.text((70, 70), title[:52], font=_font(34, True), fill=ACCENT)
    if subtitle:
        draw.text((70, 118), subtitle[:64], font=_font(26, False), fill=MUTED)

    clean = [(str(n), max(0, int(v))) for n, v in bars if str(n).strip()][:6]
    max_v = max((v for _, v in clean), default=1) or 1
    base_y = 860
    left = 100
    gap = 140
    bar_w = 90
    for i, (name, val) in enumerate(clean):
        x = left + i * gap
        h = int(420 * (val / max_v))
        color = SLICE_COLORS[i % len(SLICE_COLORS)]
        draw.rounded_rectangle([(x, base_y - h), (x + bar_w, base_y)], radius=12, fill=color)
        draw.text((x, base_y - h - 48), str(val), font=_font(28, True), fill=INK)
        # wrapped name under bar
        label = name.replace(' ', '\n')[:28]
        draw.multiline_text((x - 10, base_y + 16), label, font=_font(20, False), fill=MUTED, align='center')

    if footer:
        draw.text((70, H - 70), footer[:72], font=_font(22, False), fill=MUTED)
    return img
