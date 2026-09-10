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

Pure ffmpeg (system binary) + Pillow: ffmpeg decodes the clip already
cover-fitted to the hero box, every frame is composited in Pillow, and the
raw RGB stream goes back into ffmpeg as H.264 with the clip's own audio.
The prompt text is the stored prompt verbatim — never rewritten.
"""

from __future__ import annotations

import json
import logging
import math
import shutil
import subprocess
import tempfile
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


class ReelError(RuntimeError):
    """Composition failed in a way the operator should read (ffmpeg missing…)."""


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    duration_s: float
    has_audio: bool

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 9 / 16


@dataclass
class ReelResult:
    path: Path
    frames: int
    fps: float
    duration_s: float
    storyboard_frames: int


# ------------------------------------------------------------------ ffmpeg

def ffmpeg_exe() -> str:
    exe = shutil.which('ffmpeg')
    if exe:
        return exe
    try:  # optional pip fallback — never required
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise ReelError('ffmpeg is not installed on this machine — run: sudo apt install -y ffmpeg') from exc


def ffprobe_exe() -> str:
    exe = shutil.which('ffprobe')
    if exe:
        return exe
    raise ReelError('ffprobe is not installed on this machine — run: sudo apt install -y ffmpeg')


def _parse_rate(text: str | None) -> float:
    if not text:
        return 0.0
    if '/' in text:
        num, _, den = text.partition('/')
        try:
            return float(num) / float(den) if float(den) else 0.0
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def probe(video: Path, *, ffprobe: str | None = None) -> VideoInfo:
    cmd = [
        ffprobe or ffprobe_exe(), '-v', 'error', '-print_format', 'json',
        '-show_streams', '-show_format', str(video),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise ReelError(f'ffprobe failed: {out.stderr.strip()[:300]}')
    data = json.loads(out.stdout or '{}')
    streams = data.get('streams') or []
    video_stream = next((s for s in streams if s.get('codec_type') == 'video'), None)
    if not video_stream:
        raise ReelError('no video stream in clip')
    has_audio = any(s.get('codec_type') == 'audio' for s in streams)
    fps = _parse_rate(video_stream.get('avg_frame_rate')) or _parse_rate(video_stream.get('r_frame_rate')) or 24.0
    duration = 0.0
    for candidate in (video_stream.get('duration'), (data.get('format') or {}).get('duration')):
        try:
            duration = float(candidate or 0)
        except (TypeError, ValueError):
            duration = 0.0
        if duration > 0:
            break
    if duration <= 0:
        nb = int(video_stream.get('nb_frames') or 0)
        duration = nb / fps if nb and fps else 0.0
    return VideoInfo(
        width=int(video_stream.get('width') or 0),
        height=int(video_stream.get('height') or 0),
        fps=fps,
        duration_s=duration,
        has_audio=has_audio,
    )


def sample_frames(
    video: Path,
    info: VideoInfo,
    *,
    count: int = STORYBOARD_FRAMES,
    ffmpeg: str | None = None,
) -> list[Image.Image]:
    """`count` stills spread evenly through the clip (mid-points of equal
    slices), in the clip's own aspect ratio."""
    exe = ffmpeg or ffmpeg_exe()
    frames: list[Image.Image] = []
    duration = max(info.duration_s, 0.001)
    for i in range(count):
        t = (i + 0.5) / count * duration
        cmd = [
            exe, '-v', 'error', '-ss', f'{t:.3f}', '-i', str(video),
            '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', '-',
        ]
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=120)
        except subprocess.SubprocessError as exc:
            logger.warning('storyboard frame %s failed: %s', i, exc)
            continue
        if out.returncode != 0 or len(out.stdout) < 64:
            continue
        try:
            from io import BytesIO

            img = Image.open(BytesIO(out.stdout))
            img.load()
            frames.append(img.convert('RGB'))
        except Exception as exc:  # corrupt png from a truncated clip
            logger.warning('storyboard frame %s unreadable: %s', i, exc)
    return frames


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


def _read_exact(stream, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


# ----------------------------------------------------------------- compose

def compose_reel(
    video: Path,
    out: Path,
    *,
    prompt_text: str,
    keyword: str,
    handle: str = '@jobmaster.agency',
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
    max_fps: float = MAX_FPS,
) -> ReelResult:
    """Clip + prompt → post-ready 1080×1920 MP4 at `out`."""
    exe = ffmpeg or ffmpeg_exe()
    info = probe(video, ffprobe=ffprobe)
    fps = min(info.fps or 24.0, max_fps)
    hero_x, hero_y, hero_x2, hero_y2 = HERO_BOX
    hero_w, hero_h = hero_x2 - hero_x, hero_y2 - hero_y

    frames = sample_frames(video, info, ffmpeg=exe)
    base = base_canvas(keyword, frames, aspect=info.aspect, handle=handle)
    column = render_prompt_column(prompt_text)
    hero_mask = Image.new('L', (hero_w, hero_h), 0)
    ImageDraw.Draw(hero_mask).rounded_rectangle((0, 0, hero_w, hero_h), radius=HERO_RADIUS, fill=255)

    vf = f'scale={hero_w}:{hero_h}:force_original_aspect_ratio=increase,crop={hero_w}:{hero_h}'
    if fps < (info.fps or fps):
        vf += f',fps={fps:g}'
    decode_cmd = [exe, '-v', 'error', '-i', str(video), '-vf', vf, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    encode_cmd = [
        exe, '-y', '-v', 'error',
        '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', f'{fps:g}', '-i', '-',
    ]
    if info.has_audio:
        encode_cmd += ['-i', str(video), '-map', '0:v:0', '-map', '1:a:0', '-c:a', 'aac', '-b:a', '128k', '-shortest']
    encode_cmd += [
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'veryfast', '-crf', '20',
        '-movflags', '+faststart', str(out),
    ]

    out.parent.mkdir(parents=True, exist_ok=True)
    frame_bytes = hero_w * hero_h * 3
    written = 0
    with tempfile.TemporaryFile() as enc_err:
        decoder = subprocess.Popen(decode_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        encoder = subprocess.Popen(encode_cmd, stdin=subprocess.PIPE, stderr=enc_err)
        try:
            assert decoder.stdout is not None and encoder.stdin is not None
            while True:
                chunk = _read_exact(decoder.stdout, frame_bytes)
                if len(chunk) < frame_bytes:
                    break
                hero = Image.frombytes('RGB', (hero_w, hero_h), chunk)
                canvas = base.copy()
                canvas.paste(hero, (hero_x, hero_y), hero_mask)
                offset = scroll_offset(written / fps, info.duration_s, column.height)
                window = column.crop((0, offset, COL_W, offset + CONTENT_H))
                canvas.paste(window, (RIGHT_X, CONTENT_TOP))
                encoder.stdin.write(canvas.tobytes())
                written += 1
        finally:
            try:
                encoder.stdin.close()  # type: ignore[union-attr]
            except Exception:
                pass
            decoder.stdout.close()  # type: ignore[union-attr]
            decoder.wait(timeout=60)
            encoder.wait(timeout=600)
        enc_err.seek(0)
        err_text = enc_err.read().decode('utf-8', errors='replace').strip()
    if written == 0:
        raise ReelError('clip decoded to zero frames')
    if encoder.returncode != 0 or not out.is_file() or out.stat().st_size < 1024:
        raise ReelError(f'ffmpeg encode failed: {err_text[:300] or "no output"}')
    return ReelResult(
        path=out,
        frames=written,
        fps=fps,
        duration_s=written / fps,
        storyboard_frames=len(frames),
    )
