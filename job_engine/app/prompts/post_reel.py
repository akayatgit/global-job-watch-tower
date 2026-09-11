"""Instagram reel composer — cinematic 9:16 post (Ashok 2026-09-11).

The white card is gone. Layout matches the dark reference:

    TITLE                          ← owner-typed header, glow + shadow
    [ 9:16 clip, rounded ]  STORYBOARD
                            [6 frames, clip aspect]
                            PROMPT
                            <scrolling verbatim>
    Comment “AI” to get            ← hardcoded footer, glow + shadow
    all the prompts

Background is one storyboard frame, heavily blurred and darkened so the
theme of the clip paints the canvas. The hero box is a true 9:16 — the
old card's 900×820 hole made every vertical clip look square.

The prompt starts scrolling on frame 1 and finishes near the end (no
12 % hold). Text is the stored prompt verbatim — never rewritten.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from app.prompts.post_card import (
    H,
    W,
    _font,
    _rounded,
    cover_fit,
)
from app.prompts.reel_engines import (  # noqa: F401 — re-exported for callers
    INSTALL_HINT,
    Engine,
    ReelError,
    VideoInfo,
    describe_engine,
    require_engine,
    resolve_engine,
)

logger = logging.getLogger(__name__)

# Canvas gutters (reference: tight, not the old 90 px card margins).
MARGIN = 52
GUTTER = 28

# Header — large white, left-aligned over the hero, glow + shadow.
TITLE_Y = 58
TITLE_MAX_PT = 72
TITLE_MIN_PT = 40
TITLE_AREA_H = 150

# Hero is a true 9:16 portrait (558×992). The old HERO_BOX was 900×820.
HERO_W = 558
HERO_H = 992
HERO_X = MARGIN
HERO_Y = TITLE_AREA_H + 16
HERO_RADIUS = 32
HERO_BOX = (HERO_X, HERO_Y, HERO_X + HERO_W, HERO_Y + HERO_H)

# Right rail: storyboard on top, prompt underneath.
RIGHT_X = HERO_X + HERO_W + GUTTER
RIGHT_W = W - MARGIN - RIGHT_X
LABEL_PT = 22
STORYBOARD_FRAMES = 6
STORYBOARD_GAP = 8
STORYBOARD_RADIUS = 10
STORYBOARD_H = 460
STORYBOARD_TOP = HERO_Y + 36
PROMPT_TOP = STORYBOARD_TOP + STORYBOARD_H + 56
PROMPT_BOTTOM = HERO_Y + HERO_H
PROMPT_H = PROMPT_BOTTOM - PROMPT_TOP
# Back-compat aliases used by older tests / helpers.
COL_W = RIGHT_W
CONTENT_H = PROMPT_H
CONTENT_TOP = PROMPT_TOP

BODY_PT = 22
LINE_H = 30
# Start immediately; tiny hold only at the end so the last line can land.
SCROLL_HOLD_START = 0.0
SCROLL_HOLD_END = 0.04
SCROLL_HOLD = SCROLL_HOLD_START  # alias — tests that pass hold= still work
MAX_FPS = 30

# Hardcoded footer (Ashok 2026-09-11) — two lines, glow + shadow.
FOOTER_LINES = ('Comment “AI” to get', 'all the prompts')
FOOTER_PT = 62
FOOTER_GAP = 6
FOOTER_BOTTOM_PAD = 64

# Theme background: one storyboard frame, blurred like the reference.
BG_BLUR_RADIUS = 64
BG_DARKEN = 0.38
INK = (255, 255, 255)
INK_MUTED = (214, 214, 214)
INK_LABEL = (230, 230, 230)


@dataclass
class ReelResult:
    path: Path
    frames: int
    fps: float
    duration_s: float
    storyboard_frames: int
    engine: str = 'ffmpeg'


# ------------------------------------------------------------------ engine

def ffmpeg_exe() -> str:
    """Path of the ffmpeg binary the composer would use — kept for callers
    and deploy checks; raises ReelError with the full hunt summary when the
    machine has none (the composer itself may still run on PyAV/OpenCV)."""
    _engine, report = resolve_engine()
    if report.ffmpeg:
        return report.ffmpeg
    raise ReelError(report.hint or f'ffmpeg not found — {INSTALL_HINT}')


def probe(video: Path, *, engine: Engine | None = None) -> VideoInfo:
    return (engine or require_engine()).probe(video)


def sample_frames(
    video: Path,
    info: VideoInfo,
    *,
    count: int = STORYBOARD_FRAMES,
    engine: Engine | None = None,
) -> list[Image.Image]:
    """`count` stills spread evenly through the clip (mid-points of equal
    slices), in the clip's own aspect ratio."""
    return (engine or require_engine()).sample_frames(video, info, count=count)


# ------------------------------------------------------------------ layout

def storyboard_layout(
    aspect: float,
    *,
    box_w: int = RIGHT_W,
    box_h: int = STORYBOARD_H,
    count: int = STORYBOARD_FRAMES,
    gap: int = STORYBOARD_GAP,
) -> tuple[int, int, int, int]:
    """(cols, rows, cell_w, cell_h) — the grid of `count` cells in the clip's
    aspect ratio with the largest cells that still fit the column."""
    best: tuple[int, int, int, int] | None = None
    for cols in range(1, count + 1):
        rows = math.ceil(count / cols)
        cell_w = (box_w - (cols - 1) * gap) / cols
        cell_h = cell_w / aspect
        if rows * cell_h + (rows - 1) * gap > box_h:
            cell_h = (box_h - (rows - 1) * gap) / rows
            cell_w = cell_h * aspect
        if cell_w < 1 or cell_h < 1:
            continue
        if best is None or cell_w * cell_h > best[2] * best[3]:
            best = (cols, rows, int(cell_w), int(cell_h))
    return best or (count, 1, max(1, box_w // count), max(1, int(box_w // count / aspect)))


def draw_storyboard(
    canvas: Image.Image,
    frames: list[Image.Image],
    *,
    aspect: float,
    origin: tuple[int, int] | None = None,
) -> None:
    cols, _rows, cell_w, cell_h = storyboard_layout(aspect)
    ox, oy = origin or (RIGHT_X, STORYBOARD_TOP)
    draw = ImageDraw.Draw(canvas)
    for i in range(STORYBOARD_FRAMES):
        col, row = i % cols, i // cols
        x = ox + col * (cell_w + STORYBOARD_GAP)
        y = oy + row * (cell_h + STORYBOARD_GAP)
        if i < len(frames):
            tile = _rounded(cover_fit(frames[i], (cell_w, cell_h)), STORYBOARD_RADIUS)
            canvas.paste(tile, (x, y), tile)
        else:
            draw.rounded_rectangle(
                (x, y, x + cell_w, y + cell_h),
                radius=STORYBOARD_RADIUS,
                fill=(40, 40, 40),
            )


def wrap_by_width(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """Wrap on spaces but keep the author's line breaks (timestamped
    reverse prompts are one shot per line)."""
    lines: list[str] = []
    for block in (text or '').split('\n'):
        words = block.split()
        if not words:
            lines.append('')
            continue
        current = ''
        for word in words:
            trial = f'{current} {word}'.strip()
            if draw.textlength(trial, font=font) <= max_width or not current:
                current = trial
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines


def render_prompt_column(prompt_text: str, *, width: int = RIGHT_W) -> Image.Image:
    """The whole prompt as one tall transparent strip; the reel shows a
    window of it that slides down over the clip. Never truncated."""
    font = _font(BODY_PT)
    scratch = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    lines = wrap_by_width(scratch, prompt_text, font, width - 6)
    height = max(PROMPT_H, len(lines) * LINE_H + 8)
    strip = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(strip)
    y = 0
    for line in lines:
        if line:
            draw.text((2, y), line, font=font, fill=INK)
        y += LINE_H
    return strip


def scroll_offset(
    t: float,
    duration_s: float,
    text_h: int,
    box_h: int = PROMPT_H,
    *,
    hold: float | None = None,
    hold_start: float = SCROLL_HOLD_START,
    hold_end: float = SCROLL_HOLD_END,
) -> int:
    """Pixels the prompt strip has moved up at time t.

    Starts immediately (no lead-in hold — Ashok 2026-09-11: "damn slow
    now and starts with a delay"). Linear to the last line, tiny rest at
    the end so the closer can read it.
    """
    if hold is not None:
        hold_start = hold
        hold_end = hold
    travel = text_h - box_h
    if travel <= 0 or duration_s <= 0:
        return 0
    start = hold_start * duration_s
    end = duration_s * (1 - hold_end)
    span = max(end - start, 0.001)
    progress = min(max((t - start) / span, 0.0), 1.0)
    return int(round(progress * travel))


def blurred_backdrop(frame: Image.Image) -> Image.Image:
    """Cover-fit one storyboard still to the canvas, blur + darken to the
    reference's softness so white type sits on the clip's own colours."""
    filled = cover_fit(frame.convert('RGB'), (W, H))
    soft = filled.filter(ImageFilter.GaussianBlur(radius=BG_BLUR_RADIUS))
    return ImageEnhance.Brightness(soft).enhance(BG_DARKEN)


def _text_size(text: str, font) -> tuple[int, int]:
    scratch = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    box = scratch.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def draw_glow_text(
    canvas: Image.Image,
    xy: tuple[float, float],
    text: str,
    font,
    *,
    fill: tuple[int, int, int] = INK,
    align: str = 'left',
) -> None:
    """Crisp white type with a soft white glow and a blurred black shadow
    (the reference header / footer)."""
    tw, th = _text_size(text, font)
    x, y = xy
    if align == 'center':
        x -= tw / 2
    pad = 36
    layer = Image.new('RGBA', (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.text((pad, pad + 6), text, font=font, fill=(0, 0, 0, 200))
    shadow = layer.filter(ImageFilter.GaussianBlur(radius=14))
    glow = Image.new('RGBA', layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).text((pad, pad), text, font=font, fill=(255, 255, 255, 110))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=8))
    type_layer = Image.new('RGBA', layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(type_layer).text((pad, pad), text, font=font, fill=(*fill, 255))
    composed = Image.alpha_composite(Image.alpha_composite(shadow, glow), type_layer)
    if canvas.mode != 'RGBA':
        canvas_rgba = canvas.convert('RGBA')
        canvas_rgba.paste(composed, (int(x - pad), int(y - pad)), composed)
        canvas.paste(canvas_rgba.convert('RGB'))
    else:
        canvas.paste(composed, (int(x - pad), int(y - pad)), composed)


def fit_header(text: str, max_width: int) -> tuple[object, list[str]]:
    """Largest title that fits the width; wraps to two lines if needed."""
    raw = ' '.join((text or '').split()) or 'AI VIDEO'
    size = TITLE_MAX_PT
    scratch = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    while size >= TITLE_MIN_PT:
        font = _font(size, bold=True)
        if scratch.textlength(raw, font=font) <= max_width:
            return font, [raw]
        # Two-line wrap at the last space before the midpoint.
        words = raw.split()
        if len(words) >= 2:
            mid = max(1, len(words) // 2)
            for cut in (mid, mid - 1, mid + 1):
                if 0 < cut < len(words):
                    a, b = ' '.join(words[:cut]), ' '.join(words[cut:])
                    if scratch.textlength(a, font=font) <= max_width and scratch.textlength(b, font=font) <= max_width:
                        return font, [a, b]
        size -= 2
    font = _font(TITLE_MIN_PT, bold=True)
    return font, wrap_by_width(scratch, raw, font, max_width)[:2]


def _draw_spaced(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font, fill, tracking: int = 5) -> None:
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += int(draw.textlength(ch, font=font)) + tracking


def draw_header(canvas: Image.Image, title: str) -> None:
    font, lines = fit_header(title, W - 2 * MARGIN)
    y = TITLE_Y
    for line in lines:
        draw_glow_text(canvas, (HERO_X, y), line, font)
        y += int(_text_size(line, font)[1] * 1.05)


def draw_footer(canvas: Image.Image) -> None:
    font = _font(FOOTER_PT, bold=True)
    line_heights = [_text_size(line, font)[1] for line in FOOTER_LINES]
    block = sum(line_heights) + FOOTER_GAP * (len(FOOTER_LINES) - 1)
    y = H - FOOTER_BOTTOM_PAD - block
    for line, lh in zip(FOOTER_LINES, line_heights):
        draw_glow_text(canvas, (W / 2, y), line, font, align='center')
        y += lh + FOOTER_GAP


def base_canvas(title: str, frames: list[Image.Image], *, aspect: float, handle: str = '') -> Image.Image:
    """Everything that does not change between frames. `handle` is ignored
    — the footer is hardcoded (Ashok 2026-09-11)."""
    del handle
    source = frames[len(frames) // 2] if frames else Image.new('RGB', (W, H), (10, 10, 10))
    canvas = blurred_backdrop(source)
    draw = ImageDraw.Draw(canvas)
    draw_header(canvas, title)
    label = _font(LABEL_PT, bold=True)
    _draw_spaced(draw, (RIGHT_X, HERO_Y), 'STORYBOARD', label, INK_LABEL)
    draw_storyboard(canvas, frames, aspect=aspect)
    _draw_spaced(draw, (RIGHT_X, PROMPT_TOP - 36), 'PROMPT', label, INK_LABEL)
    draw_footer(canvas)
    return canvas


# ----------------------------------------------------------------- compose

def compose_reel(
    video: Path,
    out: Path,
    *,
    prompt_text: str,
    keyword: str,
    title: str | None = None,
    handle: str = '@jobmaster.agency',
    engine: Engine | None = None,
    max_fps: float = MAX_FPS,
) -> ReelResult:
    """Clip + prompt → post-ready 1080×1920 MP4 at `out`, on whichever
    engine this machine has (ffmpeg binary · PyAV · OpenCV)."""
    engine = engine or require_engine()
    info = engine.probe(video)
    fps = min(info.fps or 24.0, max_fps)
    header = (title or keyword or 'AI VIDEO').strip()

    frames = engine.sample_frames(video, info, count=STORYBOARD_FRAMES)
    base = base_canvas(header, frames, aspect=info.aspect, handle=handle)
    column = render_prompt_column(prompt_text)
    hero_mask = Image.new('L', (HERO_W, HERO_H), 0)
    ImageDraw.Draw(hero_mask).rounded_rectangle((0, 0, HERO_W, HERO_H), radius=HERO_RADIUS, fill=255)

    out.parent.mkdir(parents=True, exist_ok=True)
    sink = engine.open_sink(out, fps=fps, size=(W, H), audio_from=video if info.has_audio else None)
    try:
        for hero in engine.decode(video, size=(HERO_W, HERO_H), fps=fps):
            canvas = base.copy()
            rounded = hero.convert('RGBA')
            rounded.putalpha(hero_mask)
            canvas.paste(rounded, (HERO_X, HERO_Y), rounded)
            offset = scroll_offset(sink.frames / fps, info.duration_s, column.height)
            window = column.crop((0, offset, RIGHT_W, offset + PROMPT_H))
            if window.mode == 'RGBA':
                canvas.paste(window, (RIGHT_X, PROMPT_TOP), window)
            else:
                canvas.paste(window, (RIGHT_X, PROMPT_TOP))
            sink.write(canvas)
    except BaseException:
        sink.abort()
        raise
    if sink.frames == 0:
        sink.abort()
        raise ReelError('clip decoded to zero frames')
    sink.close()
    return ReelResult(
        path=out,
        frames=sink.frames,
        fps=fps,
        duration_s=sink.frames / fps,
        storyboard_frames=len(frames),
        engine=engine.name,
    )
