"""Instagram reel composer — cinematic 9:16 post (Ashok 2026-09-11).

Layout is locked to the dark Snickers reference, mapped onto 1080×1920:

    TITLE                          ← owner-typed header, centered gold serif
    [ 9:16 clip, rounded ]  STORYBOARD   ← white-bordered panel, 3×2
                            [6 frames]
                            PROMPT       ← white-bordered panel
                            <scrolling verbatim>
    Comment “AI” to get            ← hardcoded footer, centered, sits
    all the prompts                   just under the hero (not the canvas edge)

Background is one storyboard frame, heavily blurred and darkened.
The hero is a true 9:16 hole sized like the reference (~660×1173) so a
vertical clip fills the left column instead of a small postage stamp.

The prompt starts scrolling on frame 1 and finishes near the end.
Text is the stored prompt verbatim — never rewritten.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from app.prompts.post_card import (
    H,
    W,
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

FONTS_DIR = Path(__file__).resolve().parent / 'fonts'
_FONT_FILES = {
    'bold': FONTS_DIR / 'Inter-Bold.ttf',
    'medium': FONTS_DIR / 'Inter-Medium.ttf',
    'regular': FONTS_DIR / 'Inter-Regular.ttf',
    'serif': FONTS_DIR / 'PlayfairDisplay-Bold.ttf',
}
_FONT_FALLBACKS = {
    'bold': (
        '/usr/share/fonts/truetype/macos/Inter-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    ),
    'medium': (
        '/usr/share/fonts/truetype/macos/Inter-Medium.ttf',
        '/usr/share/fonts/truetype/macos/Inter-Regular.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ),
    'regular': (
        '/usr/share/fonts/truetype/macos/Inter-Regular.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ),
    'serif': (
        '/usr/share/fonts/truetype/noto/NotoSerifDisplay-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf',
    ),
}

# Snickers reference → 1080×1920. Tight side margins, large 9:16 hero,
# right rail ~1/3, the whole stack (title → hero → footer) is vertically
# centered on the canvas. Gold Playfair title, white Inter footer.
MARGIN = 36
GUTTER = 20

TITLE_MAX_PT = 74
TITLE_MIN_PT = 42
TITLE_TRACK = 2
TITLE_AREA_H = 120
TITLE_BOTTOM_MARGIN = 52  # Ashok 2026-09-11: space under the title
# Gold sampled from the aesthetic-fonts reference (mean 236,205,73).
TITLE_INK = (236, 201, 64)

HERO_W = 660
HERO_H = 1173  # 660 × 16/9
HERO_X = MARGIN
HERO_RADIUS = 28

LABEL_PT = 18
LABEL_TRACK = 2
LABEL_H = 36
STORYBOARD_FRAMES = 6
STORYBOARD_COLS = 3
STORYBOARD_ROWS = 2
STORYBOARD_GAP = 8
STORYBOARD_RADIUS = 8
STORYBOARD_H = 448

BODY_PT = 20
LINE_H = 28
SCROLL_HOLD_START = 0.0
SCROLL_HOLD_END = 0.04
SCROLL_HOLD = SCROLL_HOLD_START
MAX_FPS = 30

FOOTER_LINES = ('Comment “AI” to get', 'all the prompts')
FOOTER_PT = 58
FOOTER_TRACK = 1
FOOTER_GAP = 4
FOOTER_AFTER_HERO = 44
FOOTER_BLOCK_H = 140  # two 58pt lines + gap — used to center the stack

STACK_H = TITLE_AREA_H + TITLE_BOTTOM_MARGIN + HERO_H + FOOTER_AFTER_HERO + FOOTER_BLOCK_H
TITLE_TOP = max(24, (H - STACK_H) // 2)
HERO_Y = TITLE_TOP + TITLE_AREA_H + TITLE_BOTTOM_MARGIN
HERO_BOX = (HERO_X, HERO_Y, HERO_X + HERO_W, HERO_Y + HERO_H)
RIGHT_X = HERO_X + HERO_W + GUTTER
RIGHT_W = W - MARGIN - RIGHT_X
STORYBOARD_TOP = HERO_Y + LABEL_H
PROMPT_LABEL_TOP = STORYBOARD_TOP + STORYBOARD_H + 18
PROMPT_TOP = PROMPT_LABEL_TOP + LABEL_H
PROMPT_BOTTOM = HERO_Y + HERO_H
PROMPT_H = PROMPT_BOTTOM - PROMPT_TOP
FOOTER_Y = HERO_Y + HERO_H + FOOTER_AFTER_HERO
# Inner text width inside the white-bordered prompt panel.
PANEL_STROKE = 2
PANEL_RADIUS = 18
PANEL_PAD = 14
PROMPT_INNER_W = max(1, RIGHT_W - 2 * (PANEL_STROKE + PANEL_PAD))
# Back-compat aliases used by older tests / helpers.
COL_W = RIGHT_W
CONTENT_H = PROMPT_H
CONTENT_TOP = PROMPT_TOP

# Theme background: one storyboard frame, blurred like the reference.
BG_BLUR_RADIUS = 64
BG_DARKEN = 0.38
INK = (255, 255, 255)
INK_MUTED = (214, 214, 214)
INK_LABEL = (236, 236, 236)
PANEL_INK = (255, 255, 255)


@dataclass
class ReelResult:
    path: Path
    frames: int
    fps: float
    duration_s: float
    storyboard_frames: int
    engine: str = 'ffmpeg'


def _font(size: int, *, bold: bool = False, weight: str | None = None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Inter for body/footer; Playfair Display (Vogue serif) for the title."""
    kind = weight or ('bold' if bold else 'regular')
    paths = (_FONT_FILES.get(kind),) + _FONT_FALLBACKS.get(kind, ())
    for path in paths:
        if path and Path(path).exists():
            try:
                font = ImageFont.truetype(str(path), size)
                if kind == 'serif':
                    try:
                        font.set_variation_by_axes([700])
                    except (AttributeError, OSError, ValueError):
                        try:
                            font.set_variation_by_name('Bold')
                        except (AttributeError, OSError, ValueError, TypeError):
                            pass
                return font
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


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


# ------------------------------------------------------------------ type

def _scratch() -> ImageDraw.ImageDraw:
    return ImageDraw.Draw(Image.new('RGB', (1, 1)))


def _text_size(text: str, font) -> tuple[int, int]:
    box = _scratch().textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def spaced_width(text: str, font, tracking: int = 0) -> float:
    if not text:
        return 0.0
    draw = _scratch()
    return float(sum(draw.textlength(ch, font=font) for ch in text) + tracking * max(len(text) - 1, 0))


def render_spaced_line(text: str, font, *, fill: tuple[int, int, int] = INK, tracking: int = 0) -> Image.Image:
    """One line of tracked type on a tight transparent strip."""
    draw = _scratch()
    width = max(1, int(math.ceil(spaced_width(text, font, tracking))))
    _l, t, _r, b = draw.textbbox((0, 0), text or ' ', font=font)
    height = max(1, b - t)
    strip = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    painter = ImageDraw.Draw(strip)
    x = 0.0
    y = -t
    for i, ch in enumerate(text):
        painter.text((int(round(x)), int(y)), ch, font=font, fill=(*fill, 255))
        x += draw.textlength(ch, font=font) + (tracking if i < len(text) - 1 else 0)
    return strip


def draw_glow_text(
    canvas: Image.Image,
    xy: tuple[float, float],
    text: str,
    font,
    *,
    fill: tuple[int, int, int] = INK,
    align: str = 'left',
    tracking: int = 0,
    glow_fill: tuple[int, int, int] | None = None,
) -> None:
    """Crisp type with a soft glow (gold on the title, white on the footer)
    and a blurred black shadow."""
    if not text:
        return
    glyph = render_spaced_line(text, font, fill=fill, tracking=tracking)
    tw, th = glyph.size
    x, y = xy
    if align == 'center':
        x -= tw / 2
    pad = 36
    glow_rgb = glow_fill or fill
    layer = Image.new('RGBA', (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    shadow_src = Image.new('RGBA', layer.size, (0, 0, 0, 0))
    shadow_src.paste((0, 0, 0, 200), (pad, pad + 6, pad + tw, pad + 6 + th), glyph.split()[-1])
    shadow = shadow_src.filter(ImageFilter.GaussianBlur(radius=14))
    glow_src = Image.new('RGBA', layer.size, (0, 0, 0, 0))
    glow_src.paste((*glow_rgb, 120), (pad, pad, pad + tw, pad + th), glyph.split()[-1])
    glow = glow_src.filter(ImageFilter.GaussianBlur(radius=8))
    type_layer = Image.new('RGBA', layer.size, (0, 0, 0, 0))
    type_layer.paste(glyph, (pad, pad), glyph)
    composed = Image.alpha_composite(Image.alpha_composite(shadow, glow), type_layer)
    if canvas.mode != 'RGBA':
        canvas_rgba = canvas.convert('RGBA')
        canvas_rgba.paste(composed, (int(x - pad), int(y - pad)), composed)
        canvas.paste(canvas_rgba.convert('RGB'))
    else:
        canvas.paste(composed, (int(x - pad), int(y - pad)), composed)


def _draw_spaced(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font, fill, tracking: int = 5) -> None:
    x, y = xy
    for i, ch in enumerate(text):
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + (tracking if i < len(text) - 1 else 0)


def _draw_label(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, y: int) -> None:
    font = _font(LABEL_PT, weight='medium')
    x1, _y1, x2, _y2 = box
    width = spaced_width(text, font, LABEL_TRACK)
    _draw_spaced(draw, ((x1 + x2 - width) / 2, y), text, font, INK_LABEL, LABEL_TRACK)


def _panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    draw.rounded_rectangle(box, radius=PANEL_RADIUS, outline=PANEL_INK, width=PANEL_STROKE)


# ------------------------------------------------------------------ layout

def storyboard_layout(
    aspect: float,
    *,
    box_w: int | None = None,
    box_h: int | None = None,
    count: int = STORYBOARD_FRAMES,
    gap: int = STORYBOARD_GAP,
) -> tuple[int, int, int, int]:
    """(cols, rows, cell_w, cell_h) — 3×2 grid that fills the white panel.

    Frames are cover-fitted into the cells so a 9:16 clip still reads as
    9:16 inside each tile (the reference's compact storyboard, not tiny
    letterboxed portraits floating in black).
    """
    del aspect, count
    inner_w = box_w if box_w is not None else RIGHT_W - 2 * (PANEL_STROKE + PANEL_PAD)
    inner_h = box_h if box_h is not None else STORYBOARD_H - 2 * (PANEL_STROKE + PANEL_PAD)
    cols, rows = STORYBOARD_COLS, STORYBOARD_ROWS
    cell_w = max(1, (inner_w - (cols - 1) * gap) // cols)
    cell_h = max(1, (inner_h - (rows - 1) * gap) // rows)
    return cols, rows, cell_w, cell_h


def draw_storyboard(
    canvas: Image.Image,
    frames: list[Image.Image],
    *,
    aspect: float,
    origin: tuple[int, int] | None = None,
) -> None:
    inner_w = RIGHT_W - 2 * (PANEL_STROKE + PANEL_PAD)
    inner_h = STORYBOARD_H - 2 * (PANEL_STROKE + PANEL_PAD)
    cols, _rows, cell_w, cell_h = storyboard_layout(aspect, box_w=inner_w, box_h=inner_h)
    ox, oy = origin or (RIGHT_X + PANEL_STROKE + PANEL_PAD, STORYBOARD_TOP + PANEL_STROKE + PANEL_PAD)
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


def render_prompt_column(prompt_text: str, *, width: int = PROMPT_INNER_W) -> Image.Image:
    """The whole prompt as one tall transparent strip; the reel shows a
    window of it that slides down over the clip. Never truncated."""
    font = _font(BODY_PT)
    lines = wrap_by_width(_scratch(), prompt_text, font, width - 4)
    height = max(PROMPT_H - 2 * PANEL_PAD, len(lines) * LINE_H + 8)
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
    box_h: int = 0,
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
    box_h = box_h or max(1, PROMPT_H - 2 * PANEL_PAD)
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


def fit_header(text: str, max_width: int) -> tuple[object, list[str]]:
    """Largest centered title that fits the width; wraps to two lines if needed."""
    raw = ' '.join((text or '').split()) or 'AI VIDEO'
    size = TITLE_MAX_PT
    scratch = _scratch()
    while size >= TITLE_MIN_PT:
        font = _font(size, weight='serif')
        if spaced_width(raw, font, TITLE_TRACK) <= max_width:
            return font, [raw]
        words = raw.split()
        if len(words) >= 2:
            mid = max(1, len(words) // 2)
            for cut in (mid, mid - 1, mid + 1):
                if 0 < cut < len(words):
                    a, b = ' '.join(words[:cut]), ' '.join(words[cut:])
                    if spaced_width(a, font, TITLE_TRACK) <= max_width and spaced_width(b, font, TITLE_TRACK) <= max_width:
                        return font, [a, b]
        size -= 2
    font = _font(TITLE_MIN_PT, weight='serif')
    return font, wrap_by_width(scratch, raw, font, max_width)[:2]


def draw_header(canvas: Image.Image, title: str) -> None:
    font, lines = fit_header(title, W - 2 * MARGIN)
    if not lines:
        return
    heights = [_text_size(line, font)[1] for line in lines]
    block = sum(int(h * 1.08) for h in heights)
    y = TITLE_TOP + max(0, (TITLE_AREA_H - block) // 2)
    cx = W / 2
    for line, lh in zip(lines, heights):
        draw_glow_text(
            canvas, (cx, y), line, font, fill=TITLE_INK, align='center',
            tracking=TITLE_TRACK, glow_fill=TITLE_INK,
        )
        y += int(lh * 1.08)


def draw_footer(canvas: Image.Image) -> None:
    font = _font(FOOTER_PT, bold=True)
    line_heights = [_text_size(line, font)[1] for line in FOOTER_LINES]
    y = FOOTER_Y
    for line, lh in zip(FOOTER_LINES, line_heights):
        draw_glow_text(canvas, (W / 2, y), line, font, align='center', tracking=FOOTER_TRACK)
        y += lh + FOOTER_GAP


def base_canvas(title: str, frames: list[Image.Image], *, aspect: float, handle: str = '') -> Image.Image:
    """Everything that does not change between frames. `handle` is ignored
    — the footer is hardcoded (Ashok 2026-09-11)."""
    del handle
    source = frames[len(frames) // 2] if frames else Image.new('RGB', (W, H), (10, 10, 10))
    canvas = blurred_backdrop(source)
    draw = ImageDraw.Draw(canvas)
    draw_header(canvas, title)
    storyboard_box = (RIGHT_X, STORYBOARD_TOP, RIGHT_X + RIGHT_W, STORYBOARD_TOP + STORYBOARD_H)
    prompt_box = (RIGHT_X, PROMPT_TOP, RIGHT_X + RIGHT_W, PROMPT_BOTTOM)
    _draw_label(draw, storyboard_box, 'STORYBOARD', HERO_Y + 6)
    _panel(draw, storyboard_box)
    draw_storyboard(canvas, frames, aspect=aspect)
    _draw_label(draw, prompt_box, 'PROMPT', PROMPT_LABEL_TOP + 6)
    _panel(draw, prompt_box)
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
    prompt_window_h = max(1, PROMPT_H - 2 * PANEL_PAD)
    prompt_x = RIGHT_X + PANEL_STROKE + PANEL_PAD
    prompt_y = PROMPT_TOP + PANEL_PAD

    out.parent.mkdir(parents=True, exist_ok=True)
    sink = engine.open_sink(out, fps=fps, size=(W, H), audio_from=video if info.has_audio else None)
    try:
        for hero in engine.decode(video, size=(HERO_W, HERO_H), fps=fps):
            canvas = base.copy()
            rounded = hero.convert('RGBA')
            rounded.putalpha(hero_mask)
            canvas.paste(rounded, (HERO_X, HERO_Y), rounded)
            offset = scroll_offset(sink.frames / fps, info.duration_s, column.height, prompt_window_h)
            window = column.crop((0, offset, column.width, offset + prompt_window_h))
            if window.mode == 'RGBA':
                canvas.paste(window, (prompt_x, prompt_y), window)
            else:
                canvas.paste(window, (prompt_x, prompt_y))
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
