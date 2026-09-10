"""Instagram post card in the reference format (1080×1920 vertical):

    Comment "PERFUME" for prompts        ← engagement hook
    [ hero product image, rounded ]
    Prompt
    <prompt text, wrapped>               ← the actual value we give away
    @handle                              ← authority footer

Pure Pillow, no model. Text is the stored prompt verbatim — we never
rewrite a prompt on the card.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
BG = (246, 246, 244)
INK = (18, 18, 18)
MUTED = (96, 96, 96)
MARGIN = 90
TITLE_Y = 80
TITLE_MAX_PT = 64
TITLE_MIN_PT = 30
# The hero box is where the product image sits on the card — and where the
# AI video plays on the reel (same box, Ashok 2026-09-10).
HERO_BOX = (MARGIN, 190, W - MARGIN, 1010)
HERO_RADIUS = 48
FONT_CANDIDATES = (
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    order = FONT_CANDIDATES if bold else tuple(reversed(FONT_CANDIDATES))
    for path in order:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


def _rounded(image: Image.Image, radius: int) -> Image.Image:
    mask = Image.new('L', image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *image.size), radius=radius, fill=255)
    out = Image.new('RGBA', image.size)
    out.paste(image, (0, 0), mask)
    return out


def cover_fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale to fill `size`, then center-crop (no letterboxing)."""
    bw, bh = size
    src = image.convert('RGB')
    scale = max(bw / src.width, bh / src.height)
    frame = src.resize((max(bw, int(src.width * scale) + 1), max(bh, int(src.height * scale) + 1)))
    left = (frame.width - bw) // 2
    top = (frame.height - bh) // 2
    return frame.crop((left, top, left + bw, top + bh))


def fit_title(draw: ImageDraw.ImageDraw, text: str, max_width: int) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, float]:
    """Largest bold size (64 → 30 pt) whose rendered width fits — the hook
    line ran off the screen for long keywords (SKINCARE, 2026-09-10)."""
    size = TITLE_MAX_PT
    while True:
        font = _font(size, bold=True)
        width = draw.textlength(text, font=font)
        if width <= max_width or size <= TITLE_MIN_PT:
            return font, width
        size -= 2


def draw_title(draw: ImageDraw.ImageDraw, keyword: str) -> None:
    title = f'Comment "{keyword}" for prompts'
    font, width = fit_title(draw, title, W - 2 * MARGIN)
    draw.text(((W - width) / 2, TITLE_Y), title, font=font, fill=INK)


def keyword_for(category: str | None, title: str | None) -> str:
    """The word people comment to get the prompt — category first."""
    if category:
        return category.upper()
    first = (title or 'PROMPT').split()[0]
    return ''.join(ch for ch in first if ch.isalnum()).upper() or 'PROMPT'


def render_card(
    prompt_text: str,
    *,
    hero: Image.Image | None,
    keyword: str,
    handle: str = '@jobmaster.agency',
    max_prompt_chars: int = 900,
) -> Image.Image:
    canvas = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(canvas)
    draw_title(draw, keyword)

    hero_box = HERO_BOX
    box_size = (hero_box[2] - hero_box[0], hero_box[3] - hero_box[1])
    if hero is not None:
        frame = _rounded(cover_fit(hero, box_size), HERO_RADIUS)
        canvas.paste(frame, (hero_box[0], hero_box[1]), frame)
    else:
        draw.rounded_rectangle(hero_box, radius=HERO_RADIUS, fill=(205, 232, 218))

    head_font = _font(72, bold=True)
    draw.text((MARGIN, 1060), 'Prompt', font=head_font, fill=INK)

    body_font = _font(30)
    body = ' '.join((prompt_text or '').split())
    if len(body) > max_prompt_chars:
        body = body[:max_prompt_chars - 1].rsplit(' ', 1)[0] + '…'
    lines = textwrap.wrap(body, width=62)
    y = 1160
    for line in lines:
        if y > H - 190:
            draw.text((90, y), '…', font=body_font, fill=MUTED)
            break
        draw.text((90, y), line, font=body_font, fill=INK)
        y += 40

    foot_font = _font(48, bold=True)
    fw = draw.textlength(handle, font=foot_font)
    draw.text(((W - fw) / 2, H - 120), handle, font=foot_font, fill=INK)
    return canvas
