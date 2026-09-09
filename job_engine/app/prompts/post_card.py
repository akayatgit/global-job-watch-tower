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

    title_font = _font(64, bold=True)
    title = f'Comment "{keyword}" for prompts'
    tw = draw.textlength(title, font=title_font)
    draw.text(((W - tw) / 2, 80), title, font=title_font, fill=INK)

    hero_box = (90, 200, W - 90, 1040)
    if hero is not None:
        frame = hero.convert('RGB').copy()
        frame.thumbnail((hero_box[2] - hero_box[0], hero_box[3] - hero_box[1]))
        # Cover-fit: scale to fill, then center-crop
        scale = max((hero_box[2] - hero_box[0]) / frame.width, (hero_box[3] - hero_box[1]) / frame.height)
        frame = hero.convert('RGB').resize((int(hero.width * scale) + 1, int(hero.height * scale) + 1))
        left = (frame.width - (hero_box[2] - hero_box[0])) // 2
        top = (frame.height - (hero_box[3] - hero_box[1])) // 2
        frame = frame.crop((left, top, left + hero_box[2] - hero_box[0], top + hero_box[3] - hero_box[1]))
        canvas.paste(_rounded(frame, 48), (hero_box[0], hero_box[1]), _rounded(frame, 48))
    else:
        draw.rounded_rectangle(hero_box, radius=48, fill=(205, 232, 218))

    head_font = _font(72, bold=True)
    draw.text((90, 1090), 'Prompt', font=head_font, fill=INK)

    body_font = _font(30)
    body = ' '.join((prompt_text or '').split())
    if len(body) > max_prompt_chars:
        body = body[:max_prompt_chars - 1].rsplit(' ', 1)[0] + '…'
    lines = textwrap.wrap(body, width=62)
    y = 1190
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
