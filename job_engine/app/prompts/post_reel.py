"""Instagram reel composer — the post asset is a VIDEO, not a picture.

Ashok (2026-09-10): "wherever the image is you need to place the video …
this entire template should come out as a video … the prompt scrolls in
the video … storyboard: take the video and make six frames in the same
aspect ratio and place them next to each other in the other half."

Layout (1080×1920, same skeleton as the static card):

    Comment "SKINCARE" for prompts       ← shrinks to fit the width
    [ the AI video plays here, rounded ] ← the old hero-image box
    Storyboard        | Prompt
    [6 frames grid]   | <prompt text scrolling
                      |  over the clip's duration>
    @jobmaster.agency

Engine-agnostic (reel_engines.py): the clip is decoded already cover-fitted
to the hero box, every frame is composited in Pillow, and the RGB frames are
encoded as MP4 with the clip's own audio — by an ffmpeg binary found
anywhere on the machine, or PyAV, or OpenCV as the last resort. The prompt
text is the stored prompt verbatim — never rewritten.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from app.prompts.post_card import (
    BG,
    H,
    HERO_BOX,
    HERO_RADIUS,
    INK,
    MARGIN,
    W,
    _font,
    _rounded,
    draw_title,
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

# Below the hero box: one horizontal split into two equal columns.
GUTTER = 30
SPLIT_TOP = HERO_BOX[3] + 30
HEAD_PT = 40
CONTENT_TOP = SPLIT_TOP + 62
CONTENT_BOTTOM = H - 170
COL_W = (W - 2 * MARGIN - GUTTER) // 2
LEFT_X = MARGIN
RIGHT_X = MARGIN + COL_W + GUTTER
CONTENT_H = CONTENT_BOTTOM - CONTENT_TOP

STORYBOARD_FRAMES = 6
STORYBOARD_GAP = 10
STORYBOARD_RADIUS = 14

BODY_PT = 28
LINE_H = 38
# Fraction of the clip held still at the start and at the end of the scroll
SCROLL_HOLD = 0.12
MAX_FPS = 30
FOOTER_Y = H - 120


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
    box_w: int = COL_W,
    box_h: int = CONTENT_H,
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


def draw_storyboard(canvas: Image.Image, frames: list[Image.Image], *, aspect: float) -> None:
    from app.prompts.post_card import cover_fit

    cols, _rows, cell_w, cell_h = storyboard_layout(aspect)
    draw = ImageDraw.Draw(canvas)
    for i in range(STORYBOARD_FRAMES):
        col, row = i % cols, i // cols
        x = LEFT_X + col * (cell_w + STORYBOARD_GAP)
        y = CONTENT_TOP + row * (cell_h + STORYBOARD_GAP)
        if i < len(frames):
            tile = _rounded(cover_fit(frames[i], (cell_w, cell_h)), STORYBOARD_RADIUS)
            canvas.paste(tile, (x, y), tile)
        else:
            draw.rounded_rectangle((x, y, x + cell_w, y + cell_h), radius=STORYBOARD_RADIUS, fill=(222, 222, 218))


def wrap_by_width(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = ' '.join((text or '').split()).split(' ')
    lines: list[str] = []
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


def render_prompt_column(prompt_text: str, *, width: int = COL_W) -> Image.Image:
    """The whole prompt as one tall strip; the reel shows a window of it
    that slides down over the clip. Never truncated — long prompts scroll."""
    font = _font(BODY_PT)
    scratch = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    lines = wrap_by_width(scratch, prompt_text, font, width - 6)
    height = max(CONTENT_H, len(lines) * LINE_H + 8)
    strip = Image.new('RGB', (width, height), BG)
    draw = ImageDraw.Draw(strip)
    y = 0
    for line in lines:
        draw.text((2, y), line, font=font, fill=INK)
        y += LINE_H
    return strip


def scroll_offset(t: float, duration_s: float, text_h: int, box_h: int = CONTENT_H, *, hold: float = SCROLL_HOLD) -> int:
    """Pixels the prompt strip has moved up at time t: still for the first
    `hold` of the clip, linear to the end of the text, still for the last."""
    travel = text_h - box_h
    if travel <= 0 or duration_s <= 0:
        return 0
    start = hold * duration_s
    span = max(duration_s * (1 - 2 * hold), 0.001)
    progress = min(max((t - start) / span, 0.0), 1.0)
    return int(round(progress * travel))


def base_canvas(keyword: str, frames: list[Image.Image], *, aspect: float, handle: str) -> Image.Image:
    """Everything that does not change between frames."""
    canvas = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(canvas)
    draw_title(draw, keyword)
    head_font = _font(HEAD_PT, bold=True)
    draw.text((LEFT_X, SPLIT_TOP), 'Storyboard', font=head_font, fill=INK)
    draw.text((RIGHT_X, SPLIT_TOP), 'Prompt', font=head_font, fill=INK)
    draw_storyboard(canvas, frames, aspect=aspect)
    foot_font = _font(48, bold=True)
    fw = draw.textlength(handle, font=foot_font)
    draw.text(((W - fw) / 2, FOOTER_Y), handle, font=foot_font, fill=INK)
    return canvas


# ----------------------------------------------------------------- compose

def compose_reel(
    video: Path,
    out: Path,
    *,
    prompt_text: str,
    keyword: str,
    handle: str = '@jobmaster.agency',
    engine: Engine | None = None,
    max_fps: float = MAX_FPS,
) -> ReelResult:
    """Clip + prompt → post-ready 1080×1920 MP4 at `out`, on whichever
    engine this machine has (ffmpeg binary · PyAV · OpenCV)."""
    engine = engine or require_engine()
    info = engine.probe(video)
    fps = min(info.fps or 24.0, max_fps)
    hero_x, hero_y, hero_x2, hero_y2 = HERO_BOX
    hero_w, hero_h = hero_x2 - hero_x, hero_y2 - hero_y

    frames = engine.sample_frames(video, info, count=STORYBOARD_FRAMES)
    base = base_canvas(keyword, frames, aspect=info.aspect, handle=handle)
    column = render_prompt_column(prompt_text)
    hero_mask = Image.new('L', (hero_w, hero_h), 0)
    ImageDraw.Draw(hero_mask).rounded_rectangle((0, 0, hero_w, hero_h), radius=HERO_RADIUS, fill=255)

    out.parent.mkdir(parents=True, exist_ok=True)
    sink = engine.open_sink(out, fps=fps, size=(W, H), audio_from=video if info.has_audio else None)
    try:
        for hero in engine.decode(video, size=(hero_w, hero_h), fps=fps):
            canvas = base.copy()
            canvas.paste(hero, (hero_x, hero_y), hero_mask)
            offset = scroll_offset(sink.frames / fps, info.duration_s, column.height)
            window = column.crop((0, offset, COL_W, offset + CONTENT_H))
            canvas.paste(window, (RIGHT_X, CONTENT_TOP))
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
