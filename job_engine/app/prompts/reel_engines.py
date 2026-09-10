"""Video engines for the reel composer — use what THIS machine already has.

Ashok (2026-09-10, away from the ThinkPad): "Something for video creation
must be there, check properly." The service PATH has no `ffmpeg`, and nobody
can install one remotely. So the composer hunts instead of demanding:

1. an **ffmpeg binary** anywhere plausible — `REEL_FFMPEG`, PATH, the running
   interpreter's bin, every conda env, imageio-ffmpeg's bundled static binary
   (in any env / pipx venv / Hermes venv), Playwright's download, ~/bin … —
   and verifies it can really decode H.264 and write an MP4 before trusting
   it (Playwright's build can't, it is rejected with the reason);
2. **PyAV** (`av`) — ffmpeg's libraries linked into Python, libx264 inside;
3. **OpenCV** (`cv2`) — decodes anything, writes MPEG-4 without audio: the
   last resort so a finished clip is never left without its reel.

`describe_engine()` reports what was chosen and everywhere it looked, so the
answer is readable from the phone via `/api/prompts/stats` — no shell needed.
Every engine exposes the same four verbs (probe · sample_frames · decode ·
open_sink); the composer in post_reel.py does not care which one runs.
"""

from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Iterator, Protocol

from PIL import Image

from app import config
from app.prompts.post_card import cover_fit

logger = logging.getLogger(__name__)

# H.264 encoders in order of preference, then the universal MPEG-4 part 2.
VIDEO_ENCODERS = ('libx264', 'libopenh264', 'h264_videotoolbox', 'mpeg4')
AUDIO_ENCODERS = ('aac', 'libfdk_aac')
CONDA_ROOTS = ('anaconda3', 'miniconda3', 'miniforge3', 'mambaforge', 'micromamba', '.conda', 'conda')
# Places a static ffmpeg hides inside Python packages and tool caches
# (relative to $HOME; conda roots are expanded into these too).
HIDDEN_FFMPEG_GLOBS = (
    '.local/lib/python3*/site-packages/imageio_ffmpeg/binaries/ffmpeg-*',
    '.local/share/pipx/venvs/*/bin/ffmpeg',
    '.local/share/pipx/venvs/*/lib/python3*/site-packages/imageio_ffmpeg/binaries/ffmpeg-*',
    '.hermes/*/bin/ffmpeg',
    '.hermes/*/lib/python3*/site-packages/imageio_ffmpeg/binaries/ffmpeg-*',
    '.imageio/ffmpeg/ffmpeg-*',
    '.cache/ms-playwright/ffmpeg-*/ffmpeg-linux',
    'bin/ffmpeg',
    'ffmpeg*/ffmpeg',
    'ffmpeg*/bin/ffmpeg',
    'Downloads/ffmpeg*/ffmpeg',
    'Downloads/ffmpeg*/bin/ffmpeg',
    'tools/ffmpeg*/ffmpeg',
)
SYSTEM_DIRS = ('/usr/local/bin', '/usr/bin', '/snap/bin', '/opt/conda/bin', '/opt/ffmpeg/bin', '/opt/ffmpeg')
INSTALL_HINT = 'sudo apt install -y ffmpeg'
CACHE_TTL_S = 600


class ReelError(RuntimeError):
    """Composition failed in a way the operator should read (no engine…)."""


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


class Sink(Protocol):
    frames: int

    def write(self, image: Image.Image) -> None: ...

    def close(self) -> None: ...

    def abort(self) -> None: ...


class Engine(Protocol):
    name: str
    audio: bool

    def probe(self, video: Path) -> VideoInfo: ...

    def sample_frames(self, video: Path, info: VideoInfo, *, count: int) -> list[Image.Image]: ...

    def decode(self, video: Path, *, size: tuple[int, int], fps: float) -> Iterator[Image.Image]: ...

    def open_sink(self, out: Path, *, fps: float, size: tuple[int, int], audio_from: Path | None) -> Sink: ...


def _keep_frame(t: float, next_t: float, step: float) -> bool:
    """Time-based frame dropping for the library engines (fps cap)."""
    return t >= next_t - step * 0.25


# --------------------------------------------------------------- discovery

@dataclass
class FfmpegCaps:
    exe: str
    version: str
    video_encoder: str
    audio_encoder: str | None
    ffprobe: str | None


def _run(cmd: list[str], *, timeout: float = 20) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def _codec_listed(listing: str, name: str) -> bool:
    return re.search(rf'^\s*[A-Z.]{{6}}\s+{re.escape(name)}\b', listing or '', re.M) is not None


def inspect_ffmpeg(exe: str) -> tuple[FfmpegCaps | None, str]:
    """(caps, reason) — caps is None when this binary cannot do the job."""
    version = _run([exe, '-hide_banner', '-version'])
    if version is None or version.returncode != 0:
        return None, 'does not run'
    version_line = (version.stdout or '').splitlines()[0].strip() if version.stdout else 'ffmpeg'
    decoders = _run([exe, '-hide_banner', '-decoders'])
    if decoders is None or not _codec_listed(decoders.stdout, 'h264'):
        return None, 'no H.264 decoder (a stripped build, e.g. Playwright\'s)'
    encoders = _run([exe, '-hide_banner', '-encoders'])
    listing = encoders.stdout if encoders is not None else ''
    video_encoder = next((name for name in VIDEO_ENCODERS if _codec_listed(listing, name)), None)
    if not video_encoder:
        return None, 'no MP4 video encoder (libx264 / libopenh264 / mpeg4)'
    audio_encoder = next((name for name in AUDIO_ENCODERS if _codec_listed(listing, name)), None)
    sibling = Path(exe).with_name('ffprobe')
    ffprobe = str(sibling) if sibling.is_file() and os.access(sibling, os.X_OK) else shutil.which('ffprobe')
    return FfmpegCaps(exe=exe, version=version_line, video_encoder=video_encoder, audio_encoder=audio_encoder, ffprobe=ffprobe), 'ok'


def ffmpeg_candidates(home: Path | None = None) -> list[str]:
    """Every path that might be an ffmpeg binary, most trustworthy first.
    Existence is checked; capability is not (see inspect_ffmpeg)."""
    home = home or Path.home()
    found: list[str] = []

    def add(path: str | Path | None) -> None:
        if not path:
            return
        p = Path(path)
        if p.is_file() and os.access(p, os.X_OK):
            resolved = str(p)
            if resolved not in found:
                found.append(resolved)

    add(config.REEL_FFMPEG or None)
    add(shutil.which('ffmpeg'))
    add(Path(sys.executable).parent / 'ffmpeg')
    for var in ('CONDA_PREFIX',):
        if os.environ.get(var):
            add(Path(os.environ[var]) / 'bin' / 'ffmpeg')
    if os.environ.get('CONDA_EXE'):
        add(Path(os.environ['CONDA_EXE']).parent / 'ffmpeg')
    for root_name in CONDA_ROOTS:
        root = home / root_name
        if not root.is_dir():
            continue
        add(root / 'bin' / 'ffmpeg')
        for pattern in ('envs/*/bin/ffmpeg', 'pkgs/ffmpeg-*/bin/ffmpeg',
                        'lib/python3*/site-packages/imageio_ffmpeg/binaries/ffmpeg-*',
                        'envs/*/lib/python3*/site-packages/imageio_ffmpeg/binaries/ffmpeg-*'):
            for hit in sorted(glob.glob(str(root / pattern))):
                add(hit)
    try:  # the running interpreter's own imageio-ffmpeg, if any
        import imageio_ffmpeg  # type: ignore

        add(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    for pattern in HIDDEN_FFMPEG_GLOBS:
        for hit in sorted(glob.glob(str(home / pattern))):
            add(hit)
    for d in (home / '.local' / 'bin', *map(Path, SYSTEM_DIRS)):
        add(d / 'ffmpeg')
    return found


def python_libs() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in ('av', 'cv2', 'imageio_ffmpeg', 'numpy'):
        try:
            module = __import__(name)
            versions[name] = str(getattr(module, '__version__', 'present'))
        except Exception:
            versions[name] = None
    return versions


# ----------------------------------------------------------- ffmpeg engine

_DURATION_RE = re.compile(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)')
_VIDEO_RE = re.compile(r'Stream #\d+:\d+.*?Video:.*?\b(\d{2,5})x(\d{2,5})\b')
_FPS_RE = re.compile(r'(\d+(?:\.\d+)?)\s*fps')
_TBR_RE = re.compile(r'(\d+(?:\.\d+)?)\s*tbr')
_AUDIO_RE = re.compile(r'Stream #\d+:\d+.*?Audio:')


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


def parse_ffmpeg_banner(stderr: str) -> VideoInfo:
    """`ffmpeg -i clip` prints everything ffprobe would — read it when there
    is no ffprobe next to the binary (imageio-ffmpeg ships none)."""
    text = stderr or ''
    video = _VIDEO_RE.search(text)
    if not video:
        raise ReelError('no video stream in clip')
    video_line = text[video.start():].split('\n', 1)[0]
    fps = _parse_rate((_FPS_RE.search(video_line) or _TBR_RE.search(video_line) or [None, None])[1]) or 24.0
    duration = 0.0
    dur = _DURATION_RE.search(text)
    if dur:
        h, m, s = dur.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)
    return VideoInfo(
        width=int(video.group(1)), height=int(video.group(2)), fps=fps,
        duration_s=duration, has_audio=_AUDIO_RE.search(text) is not None,
    )


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


class FfmpegSink:
    def __init__(self, cmd: list[str], out: Path) -> None:
        self.out = out
        self.frames = 0
        self._err = tempfile.TemporaryFile()
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=self._err)

    def write(self, image: Image.Image) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(image.tobytes())
        self.frames += 1

    def _finish(self, *, timeout: float) -> str:
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except Exception:
            pass
        try:
            self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        self._err.seek(0)
        text = self._err.read().decode('utf-8', errors='replace').strip()
        self._err.close()
        return text

    def close(self) -> None:
        err_text = self._finish(timeout=600)
        if self._proc.returncode != 0 or not self.out.is_file() or self.out.stat().st_size < 1024:
            raise ReelError(f'ffmpeg encode failed: {err_text[:300] or "no output"}')

    def abort(self) -> None:
        self._proc.kill()
        self._finish(timeout=10)
        self.out.unlink(missing_ok=True)


class FfmpegEngine:
    name = 'ffmpeg'

    def __init__(self, caps: FfmpegCaps) -> None:
        self.caps = caps
        self.exe = caps.exe
        self.ffprobe = caps.ffprobe
        self.audio = caps.audio_encoder is not None

    def probe(self, video: Path) -> VideoInfo:
        if self.ffprobe:
            return probe_with_ffprobe(video, self.ffprobe)
        out = _run([self.exe, '-hide_banner', '-i', str(video)], timeout=120)
        if out is None:
            raise ReelError('ffmpeg could not read the clip')
        return parse_ffmpeg_banner(out.stderr)

    def sample_frames(self, video: Path, info: VideoInfo, *, count: int) -> list[Image.Image]:
        from io import BytesIO

        frames: list[Image.Image] = []
        duration = max(info.duration_s, 0.001)
        for i in range(count):
            t = (i + 0.5) / count * duration
            cmd = [
                self.exe, '-v', 'error', '-ss', f'{t:.3f}', '-i', str(video),
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
                img = Image.open(BytesIO(out.stdout))
                img.load()
                frames.append(img.convert('RGB'))
            except Exception as exc:  # corrupt png from a truncated clip
                logger.warning('storyboard frame %s unreadable: %s', i, exc)
        return frames

    def decode(self, video: Path, *, size: tuple[int, int], fps: float) -> Iterator[Image.Image]:
        w, h = size
        vf = f'scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps:g}'
        cmd = [self.exe, '-v', 'error', '-i', str(video), '-vf', vf, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
        frame_bytes = w * h * 3
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            assert proc.stdout is not None
            while True:
                chunk = _read_exact(proc.stdout, frame_bytes)
                if len(chunk) < frame_bytes:
                    break
                yield Image.frombytes('RGB', (w, h), chunk)
        finally:
            if proc.stdout:
                proc.stdout.close()
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()

    def open_sink(self, out: Path, *, fps: float, size: tuple[int, int], audio_from: Path | None) -> Sink:
        w, h = size
        cmd = [
            self.exe, '-y', '-v', 'error',
            '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{w}x{h}', '-r', f'{fps:g}', '-i', '-',
        ]
        if audio_from is not None and self.audio:
            cmd += ['-i', str(audio_from), '-map', '0:v:0', '-map', '1:a:0',
                    '-c:a', self.caps.audio_encoder or 'aac', '-b:a', '128k', '-shortest']
        encoder = self.caps.video_encoder
        if encoder == 'libx264':
            cmd += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20']
        elif encoder == 'mpeg4':
            cmd += ['-c:v', 'mpeg4', '-q:v', '3']
        else:
            cmd += ['-c:v', encoder, '-b:v', '6M']
        cmd += ['-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(out)]
        return FfmpegSink(cmd, out)


def probe_with_ffprobe(video: Path, ffprobe: str) -> VideoInfo:
    import json

    cmd = [ffprobe, '-v', 'error', '-print_format', 'json', '-show_streams', '-show_format', str(video)]
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
        width=int(video_stream.get('width') or 0), height=int(video_stream.get('height') or 0),
        fps=fps, duration_s=duration, has_audio=has_audio,
    )


# ------------------------------------------------------------- PyAV engine

class PyAvSink:
    def __init__(self, out: Path, *, fps: float, size: tuple[int, int], audio_from: Path | None) -> None:
        import av

        self.out = out
        self.frames = 0
        self._fps = fps
        rate = Fraction(fps).limit_denominator(1001)
        self._container = av.open(str(out), 'w', options={'movflags': 'faststart'})
        codec = 'libx264' if _av_has_codec('libx264') else 'h264'
        self._stream = self._container.add_stream(codec, rate=rate)
        self._stream.width, self._stream.height = size
        self._stream.pix_fmt = 'yuv420p'
        if codec == 'libx264':
            self._stream.options = {'crf': '20', 'preset': 'veryfast'}
        self._audio_src = None
        self._audio_in = None
        self._audio_out = None
        if audio_from is not None:
            try:
                self._audio_src = av.open(str(audio_from))
                self._audio_in = self._audio_src.streams.audio[0]
                adder = getattr(self._container, 'add_stream_from_template', None)
                self._audio_out = adder(self._audio_in) if adder else self._container.add_stream(template=self._audio_in)
            except Exception as exc:  # no audio beats no reel
                logger.warning('reel audio copy unavailable: %s', exc)
                self._audio_out = None

    def write(self, image: Image.Image) -> None:
        import av

        # No pts/time_base by hand — PyAV numbers frames itself; setting them
        # against the muxer's rescaled time base is an EINVAL at mux time.
        frame = av.VideoFrame.from_image(image.convert('RGB'))
        for packet in self._stream.encode(frame):
            self._container.mux(packet)
        self.frames += 1

    def _copy_audio(self) -> None:
        if self._audio_out is None or self._audio_src is None or self._audio_in is None:
            return
        limit = self.frames / self._fps
        for packet in self._audio_src.demux(self._audio_in):
            if packet.dts is None:
                continue
            if packet.pts is not None and float(packet.pts * packet.time_base) > limit:
                break  # -shortest: never let the audio outlive the picture
            packet.stream = self._audio_out
            self._container.mux(packet)

    def close(self) -> None:
        try:
            for packet in self._stream.encode():
                self._container.mux(packet)
            self._copy_audio()
        finally:
            self._container.close()
            if self._audio_src is not None:
                self._audio_src.close()
        if not self.out.is_file() or self.out.stat().st_size < 1024:
            raise ReelError('PyAV encode produced no output')

    def abort(self) -> None:
        try:
            self._container.close()
        except Exception:
            pass
        if self._audio_src is not None:
            self._audio_src.close()
        self.out.unlink(missing_ok=True)


def _av_has_codec(name: str) -> bool:
    try:
        import av

        av.codec.Codec(name, 'w')
        return True
    except Exception:
        return False


class PyAvEngine:
    name = 'pyav'
    audio = True

    def probe(self, video: Path) -> VideoInfo:
        import av

        try:
            container = av.open(str(video))
        except Exception as exc:
            raise ReelError(f'PyAV could not open the clip: {exc}') from exc
        with container:
            stream = next(iter(container.streams.video), None)
            if stream is None:
                raise ReelError('no video stream in clip')
            fps = float(stream.average_rate or stream.guessed_rate or stream.base_rate or 24)
            duration = float(stream.duration * stream.time_base) if stream.duration else 0.0
            if duration <= 0 and container.duration:
                duration = container.duration / 1_000_000
            if duration <= 0 and stream.frames:
                duration = stream.frames / fps
            return VideoInfo(
                width=int(stream.codec_context.width), height=int(stream.codec_context.height),
                fps=fps or 24.0, duration_s=duration, has_audio=bool(container.streams.audio),
            )

    def _frames(self, video: Path) -> Iterator[tuple[float, Image.Image]]:
        import av

        with av.open(str(video)) as container:
            stream = container.streams.video[0]
            stream.thread_type = 'AUTO'
            in_fps = float(stream.average_rate or stream.guessed_rate or 24)
            for index, frame in enumerate(container.decode(stream)):
                t = frame.time if frame.time is not None else index / in_fps
                yield float(t), frame.to_image()

    def sample_frames(self, video: Path, info: VideoInfo, *, count: int) -> list[Image.Image]:
        return _sample_by_time(self._frames(video), info, count)

    def decode(self, video: Path, *, size: tuple[int, int], fps: float) -> Iterator[Image.Image]:
        step = 1 / fps
        next_t = 0.0
        for t, image in self._frames(video):
            if not _keep_frame(t, next_t, step):
                continue
            next_t += step
            yield cover_fit(image, size)

    def open_sink(self, out: Path, *, fps: float, size: tuple[int, int], audio_from: Path | None) -> Sink:
        return PyAvSink(out, fps=fps, size=size, audio_from=audio_from)


def _sample_by_time(frames: Iterator[tuple[float, Image.Image]], info: VideoInfo, count: int) -> list[Image.Image]:
    duration = max(info.duration_s, 0.001)
    targets = [(i + 0.5) / count * duration for i in range(count)]
    picked: list[Image.Image] = []
    last: Image.Image | None = None
    for t, image in frames:
        last = image
        while len(picked) < count and t >= targets[len(picked)] - 1e-6:
            picked.append(image)
    while last is not None and len(picked) < count:  # duration overstated → repeat the tail
        picked.append(last)
    return picked


# ----------------------------------------------------------- OpenCV engine

class OpenCvSink:
    FOURCCS = ('avc1', 'mp4v')

    def __init__(self, out: Path, *, fps: float, size: tuple[int, int]) -> None:
        import cv2
        import numpy as np

        self._np = np
        self.out = out
        self.frames = 0
        self.fourcc = None
        quiet = getattr(cv2, 'setLogLevel', None)
        if quiet:
            quiet(0)
        for fourcc in self.FOURCCS:
            writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*fourcc), float(fps), size)
            if writer.isOpened():
                self._writer = writer
                self.fourcc = fourcc
                break
            writer.release()
        else:
            raise ReelError('OpenCV has no MP4 encoder on this machine')

    def write(self, image: Image.Image) -> None:
        rgb = self._np.asarray(image.convert('RGB'))
        self._writer.write(self._np.ascontiguousarray(rgb[:, :, ::-1]))
        self.frames += 1

    def close(self) -> None:
        self._writer.release()
        if not self.out.is_file() or self.out.stat().st_size < 1024:
            raise ReelError('OpenCV encode produced no output')

    def abort(self) -> None:
        try:
            self._writer.release()
        except Exception:
            pass
        self.out.unlink(missing_ok=True)


class OpenCvEngine:
    name = 'opencv'
    audio = False

    def probe(self, video: Path) -> VideoInfo:
        import cv2

        cap = cv2.VideoCapture(str(video))
        try:
            if not cap.isOpened():
                raise ReelError('OpenCV could not open the clip')
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0) or 24.0
            count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        finally:
            cap.release()
        if not width or not height:
            raise ReelError('no video stream in clip')
        return VideoInfo(width=width, height=height, fps=fps, duration_s=count / fps if count else 0.0, has_audio=False)

    def _frames(self, video: Path) -> Iterator[tuple[float, Image.Image]]:
        import cv2

        cap = cv2.VideoCapture(str(video))
        try:
            in_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0) or 24.0
            index = 0
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                yield index / in_fps, Image.fromarray(frame[:, :, ::-1])
                index += 1
        finally:
            cap.release()

    def sample_frames(self, video: Path, info: VideoInfo, *, count: int) -> list[Image.Image]:
        return _sample_by_time(self._frames(video), info, count)

    def decode(self, video: Path, *, size: tuple[int, int], fps: float) -> Iterator[Image.Image]:
        step = 1 / fps
        next_t = 0.0
        for t, image in self._frames(video):
            if not _keep_frame(t, next_t, step):
                continue
            next_t += step
            yield cover_fit(image, size)

    def open_sink(self, out: Path, *, fps: float, size: tuple[int, int], audio_from: Path | None) -> Sink:
        return OpenCvSink(out, fps=fps, size=size)


# ------------------------------------------------------------- resolution

@dataclass
class EngineReport:
    engine: str  # ffmpeg | pyav | opencv | none
    ffmpeg: str | None = None
    ffprobe: str | None = None
    version: str | None = None
    video_codec: str | None = None
    audio: bool = False
    python: str = sys.executable
    libs: dict[str, str | None] = field(default_factory=dict)
    searched: list[str] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)
    hint: str | None = None
    checked_at: float = field(default_factory=time.time)

    @property
    def ok(self) -> bool:
        return self.engine != 'none'

    def as_dict(self) -> dict:
        return {
            'engine': self.engine,
            'ok': self.ok,
            'ffmpeg': self.ffmpeg,
            'ffprobe': self.ffprobe,
            'version': self.version,
            'video_codec': self.video_codec,
            'audio': self.audio,
            'python': self.python,
            'libs': dict(self.libs),
            'searched': list(self.searched),
            'rejected': dict(self.rejected),
            'hint': self.hint,
        }

    def summary(self) -> str:
        if self.engine == 'ffmpeg':
            return f'ffmpeg at {self.ffmpeg} ({self.video_codec}{", audio" if self.audio else ", no audio encoder"})'
        if self.engine == 'pyav':
            return f'PyAV {self.libs.get("av")} (libx264 in-process, audio copied)'
        if self.engine == 'opencv':
            return f'OpenCV {self.libs.get("cv2")} (MPEG-4, silent reel — last resort)'
        return f'none — {self.hint}'


def discover(home: Path | None = None) -> tuple[Engine | None, EngineReport]:
    report = EngineReport(engine='none', libs=python_libs())
    for exe in ffmpeg_candidates(home):
        report.searched.append(exe)
        caps, reason = inspect_ffmpeg(exe)
        if caps is None:
            report.rejected[exe] = reason
            continue
        report.engine = 'ffmpeg'
        report.ffmpeg = caps.exe
        report.ffprobe = caps.ffprobe
        report.version = caps.version
        report.video_codec = caps.video_encoder
        report.audio = caps.audio_encoder is not None
        return FfmpegEngine(caps), report
    if report.libs.get('av') and _av_has_codec('libx264'):
        report.engine = 'pyav'
        report.version = f'PyAV {report.libs["av"]}'
        report.video_codec = 'libx264'
        report.audio = True
        return PyAvEngine(), report
    if report.libs.get('cv2') and report.libs.get('numpy'):
        report.engine = 'opencv'
        report.version = f'OpenCV {report.libs["cv2"]}'
        report.video_codec = 'mpeg4'
        report.audio = False
        return OpenCvEngine(), report
    report.hint = (
        f'no video engine: ffmpeg not found on PATH / conda envs / imageio-ffmpeg / Playwright '
        f'({len(report.searched)} candidate(s) checked), and neither PyAV (av) nor OpenCV (cv2) imports '
        f'in {sys.executable}. Fix: {INSTALL_HINT}'
    )
    return None, report


_lock = threading.Lock()
_cached: tuple[Engine | None, EngineReport] | None = None


def resolve_engine(*, force: bool = False) -> tuple[Engine | None, EngineReport]:
    """Cached discovery — a failed hunt is retried after CACHE_TTL_S so a
    later install is picked up without restarting the worker."""
    global _cached
    with _lock:
        if not force and _cached is not None:
            engine, report = _cached
            if engine is not None or time.time() - report.checked_at < CACHE_TTL_S:
                return _cached
        _cached = discover()
        logger.info('reel engine: %s', _cached[1].summary())
        return _cached


def require_engine() -> Engine:
    engine, report = resolve_engine()
    if engine is None:
        raise ReelError(report.hint or f'no video engine — {INSTALL_HINT}')
    return engine


def describe_engine(*, force: bool = False) -> dict:
    return resolve_engine(force=force)[1].as_dict()


def main() -> int:
    """`python -m app.prompts.reel_engines` — the deploy script's check and a
    one-line answer for anyone with a shell. Exit 0 when an engine exists."""
    engine, report = discover()
    print(report.summary())
    if engine is None:
        print('looked at: ' + (', '.join(report.searched) or 'nothing executable'))
        for path, why in report.rejected.items():
            print(f'  rejected {path}: {why}')
        print('python libs: ' + ', '.join(f'{k}={v or "absent"}' for k, v in report.libs.items()))
    return 0 if engine is not None else 1


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
