"""Reverse prompt — a best-performing product video → the prompt behind it.

Ashok (2026-09-10): "/igtovid or /pintovid … ask for the Instagram or
Pinterest url, download the video, take 6 frames, pass the video to Gemini
to get a timestamp-based prompt … place the video, the prompt and the
screenshots as storyboard frames in the same final template and render the
final video. This is a very important feature — this is the best
performing post for which we get the reverse prompt and post it."

Pipeline (worker, `app.tasks.reverse_prompt_video`):

    URL ─▶ fetch_video ─▶ stored clip ─▶ describe_video (Gemini / GPT-6
    Astra / Claude Fable 5 each get the video file) ─▶ keyword +
    timestamped prompt ─▶ cut-reference JPEGs ─▶ refine_prompt_with_frames
    (same video + ≤10 of those JPEGs) ─▶ post_reel.compose_reel ─▶ reel MP4

Downloading: plain HTTP with a browser UA first (Pinterest pages carry the
mp4 in their JSON; direct .mp4 links pass through), then the logged-in
stealth Chrome profile for Instagram, then ffmpeg for HLS playlists. When
a page hides the file, the owner can forward the video itself in Telegram
— same pipeline from the stored clip onward.

The prompt is what the vision model wrote, stored and shown verbatim —
this is the one place in Prompt Tower where an AI authors a prompt, and
it is a creative reverse-engineering, not a fact about the world.
"""

from __future__ import annotations

import base64
import html as html_lib
import json
import logging
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app import config

logger = logging.getLogger(__name__)

USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
    '(KHTML, like Gecko) Version/17.4 Safari/605.1.15'
)
HTTP_TIMEOUT_S = 60
DOWNLOAD_TIMEOUT_S = 600
# Hard cap around sources.browser_fetch (90s page timeout). Must not use
# ThreadPoolExecutor as a context manager — shutdown(wait=True) would sit
# on a hung Chrome until the worker dies (reverse #14, 2026-09-11).
BROWSER_FETCH_HARD_TIMEOUT_S = 100
MIN_VIDEO_BYTES = 50_000
DESCRIBE_BUDGET_S = 600
DEFAULT_KEYWORD = 'PRODUCT'
# Gemini 2.5 Flash thinking shares max_output_tokens. Reverse #7 (2026-09-11)
# died mid-JSON at 4096 — thinking ate the budget. We keep 32k output so
# thinking can come back. Ashok (2026-09-11): prompts MUST stay strictly
# under 3000 characters including spaces — thinking plans that cut.
MAX_OUTPUT_TOKENS = 32768
THINKING_BUDGET = 8192
PROMPT_CHAR_LIMIT = 3000
PROMPT_MAX_CHARS = PROMPT_CHAR_LIMIT - 1  # stored / fitted max (2999)
STYLE_LINE_RE = re.compile(r'(?im)(?:^|\n)(style:\s*.+)$')
ENGINE_GEMINI = 'gemini'
ENGINE_ASTRA = 'astra'
ENGINE_FABLE = 'fable'
VISION_ENGINE_KEYS = (ENGINE_GEMINI, ENGINE_ASTRA, ENGINE_FABLE)
VISION_LABELS = {
    ENGINE_GEMINI: 'Gemini',
    ENGINE_ASTRA: 'GPT-6 Astra',
    ENGINE_FABLE: 'Claude Fable 5',
}
# Data-URI ceiling: Telegram's bot download is 20 MB; Instagram reels sit
# well under this. Larger clips ride a public .mp4 URL so Gemini can see
# the suffix (Replicate's Files API URL has none — that is what killed #1).
DATA_URI_MAX_BYTES = 20 * 1024 * 1024
VIDEO_MIME = {
    '.mp4': 'video/mp4',
    '.m4v': 'video/mp4',
    '.mov': 'video/quicktime',
    '.webm': 'video/webm',
    '.mpeg': 'video/mpeg',
    '.mpg': 'video/mpeg',
}

URL_RE = re.compile(r'https?://[^\s<>"\']+', re.I)
INSTAGRAM_RE = re.compile(r'https?://(?:www\.|m\.)?instagram\.com/(?:[\w.]+/)?(?:reels?|p|tv)/([\w-]+)', re.I)
PINTEREST_RE = re.compile(r'https?://(?:[\w-]+\.)?pinterest\.[a-z.]+/pin/([\w-]+)', re.I)
PINIT_RE = re.compile(r'https?://pin\.it/[\w-]+', re.I)
DIRECT_RE = re.compile(r'\.(mp4|mov|m4v|webm|m3u8)(?:$|[?#])', re.I)

# Ordered: what the page says its video is → JSON the apps embed → any mp4.
MEDIA_PATTERNS = (
    re.compile(r'<meta[^>]+property=["\']og:video(?::secure_url)?["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:video(?::secure_url)?["\']', re.I),
    re.compile(r'<meta[^>]+property=["\']twitter:player:stream["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'"video_url"\s*:\s*"([^"]+)"'),
    re.compile(r'"video_versions"\s*:\s*\[\s*\{[^}]*?"url"\s*:\s*"([^"]+)"'),
    re.compile(r'"playable_url(?:_quality_hd)?"\s*:\s*"([^"]+)"'),
    re.compile(r'"contentUrl"\s*:\s*"([^"]+)"'),
    re.compile(r'"V_720P"\s*:\s*\{[^}]*?"url"\s*:\s*"([^"]+)"'),
    re.compile(r'"V_[A-Z0-9]+"\s*:\s*\{[^}]*?"url"\s*:\s*"([^"]+\.mp4[^"]*)"'),
    re.compile(r'"V_HLSV\d"\s*:\s*\{[^}]*?"url"\s*:\s*"([^"]+\.m3u8[^"]*)"'),
    re.compile(r'(https?:\\?/\\?/[^"\s<>\']+?\.mp4(?:\?[^"\s<>\']*)?)', re.I),
)


class ReverseError(RuntimeError):
    """Operator-readable failure (no video on that page, model refused…)."""


@dataclass
class FetchedVideo:
    data: bytes
    media_url: str
    platform: str


@dataclass
class ReverseReading:
    keyword: str
    prompt: str
    model: str
    raw: str
    cuts: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class ReferenceFrame:
    t: float
    key: str
    filename: str


# ------------------------------------------------------------------ URLs

def find_url(text: str) -> str | None:
    match = URL_RE.search(text or '')
    return match.group(0).rstrip('.,;)') if match else None


def detect_platform(url: str) -> str | None:
    """instagram | pinterest | direct | None (not something we can fetch)."""
    if not url or not url.lower().startswith(('http://', 'https://')):
        return None
    if INSTAGRAM_RE.match(url):
        return 'instagram'
    if PINTEREST_RE.match(url) or PINIT_RE.match(url):
        return 'pinterest'
    if DIRECT_RE.search(url.split('#', 1)[0]):
        return 'direct'
    return None


def canonical_url(url: str) -> str:
    """Instagram share links carry tracking (?igsh=…) — keep only the post.
    Pinterest / direct links are left alone (their query may matter)."""
    match = INSTAGRAM_RE.match(url or '')
    if match:
        kind = re.search(r'/(reels?|p|tv)/', url, re.I)
        return f'https://www.instagram.com/{(kind.group(1) if kind else "reel").lower()}/{match.group(1)}/'
    return (url or '').strip()


def _unescape(raw: str) -> str:
    text = raw.replace('\\/', '/').replace('\\u0026', '&').replace('\\u003d', '=').replace('\\u0025', '%')
    return html_lib.unescape(text).strip()


def extract_media_urls(page_html: str) -> list[str]:
    """Every downloadable video URL the page exposes, best first (mp4
    before HLS, page-declared before scraped)."""
    found: list[str] = []
    for pattern in MEDIA_PATTERNS:
        for match in pattern.finditer(page_html or ''):
            url = _unescape(match.group(1))
            if not url.lower().startswith('http') or url in found:
                continue
            found.append(url)
    return sorted(found, key=lambda u: '.m3u8' in u.lower())


# -------------------------------------------------------------- download

def http_get(url: str, *, referer: str | None = None, max_bytes: int | None = None, timeout: float = HTTP_TIMEOUT_S) -> bytes:
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    if referer:
        headers['Referer'] = referer
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        if max_bytes is None:
            return resp.read()
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ReverseError(f'video is larger than {max_bytes // (1024 * 1024)} MB — send a shorter clip')
            chunks.append(chunk)
        return b''.join(chunks)


def hls_to_mp4(playlist_url: str, *, referer: str | None, ffmpeg: str, max_bytes: int) -> bytes:
    """Pinterest often exposes only an HLS playlist — ffmpeg stitches it.

    Copy first (fast). If the playlist is HEVC/broken, transcode to
    H.264 so Gemini can actually watch it (reverse #16, E001).
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'clip.mp4'
        headers = f'User-Agent: {USER_AGENT}\r\n' + (f'Referer: {referer}\r\n' if referer else '')
        common = [ffmpeg, '-y', '-v', 'error', '-headers', headers, '-i', playlist_url]
        attempts = (
            ['-c', 'copy', '-bsf:a', 'aac_adtstoasc', '-movflags', '+faststart', str(out)],
            [
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-movflags', '+faststart', str(out),
            ],
        )
        last_err = ''
        for extra in attempts:
            result = subprocess.run(
                common + extra, capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT_S,
            )
            if result.returncode == 0 and out.is_file() and out.stat().st_size >= MIN_VIDEO_BYTES:
                if out.stat().st_size > max_bytes:
                    raise ReverseError(
                        f'video is larger than {max_bytes // (1024 * 1024)} MB — send a shorter clip'
                    )
                return out.read_bytes()
            last_err = (result.stderr or '').strip()[:200]
            out.unlink(missing_ok=True)
        raise ReverseError(f'HLS download failed: {last_err}')


def looks_like_video(data: bytes) -> bool:
    head = data[:64]
    return b'ftyp' in head or head.startswith(b'\x1aE\xdf\xa3') or head.startswith(b'RIFF')


_UNSAFE_VIDEO_RE = re.compile(r'video:\s*(hevc|h265|h\.265|vp9|vp8|av1|mpeg4|theora|wmv)', re.I)
_H264_VIDEO_RE = re.compile(r'video:\s*(h264|avc1|avc)', re.I)


def _ffmpeg_exe() -> str | None:
    try:
        from app.prompts import post_reel

        return post_reel.ffmpeg_exe()
    except Exception:
        return None


def _run_ffmpeg(cmd: list[str], *, timeout: float = 600, run=None):
    if run is not None:
        return run(cmd)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def probe_video_banner(path: Path, *, ffmpeg: str, run=None) -> str:
    result = _run_ffmpeg([ffmpeg, '-hide_banner', '-i', str(path)], timeout=60, run=run)
    return f'{result.stderr or ""}\n{result.stdout or ""}'


def is_gemini_safe_banner(banner: str) -> bool:
    """Gemini-on-Replicate chokes on HEVC / VP9 Pinterest pins (E001)."""
    text = banner or ''
    if _UNSAFE_VIDEO_RE.search(text):
        return False
    return bool(_H264_VIDEO_RE.search(text))


def prepare_vision_clip(
    path: Path,
    *,
    ffmpeg: str | None = None,
    force: bool = False,
    log: Callable[[str], None] | None = None,
    run=None,
) -> bool:
    """Rewrite `path` in place as H.264 + yuv420p + AAC when Gemini
    would refuse the original (Pinterest HLS/HEVC → E001).

    Returns True when the file changed. Missing ffmpeg is a no-op.
    """
    exe = ffmpeg or _ffmpeg_exe()
    if not exe or not path.is_file():
        return False
    if not force:
        banner = probe_video_banner(path, ffmpeg=exe, run=run)
        if is_gemini_safe_banner(banner):
            return False
        if log:
            codec = (_UNSAFE_VIDEO_RE.search(banner) or _H264_VIDEO_RE.search(banner))
            log(f'remuxing clip for Gemini (was {codec.group(1) if codec else "unknown codec"})')
    tmp = path.with_name(path.name + '.gemini.mp4')
    cmd = [
        exe, '-y', '-v', 'error', '-i', str(path),
        '-map', '0:v:0', '-map', '0:a:0?',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-ac', '2', '-b:a', '128k',
        '-movflags', '+faststart', str(tmp),
    ]
    result = _run_ffmpeg(cmd, timeout=DOWNLOAD_TIMEOUT_S, run=run)
    if result.returncode != 0 or not tmp.is_file() or tmp.stat().st_size < MIN_VIDEO_BYTES:
        tmp.unlink(missing_ok=True)
        if log:
            log(f'Gemini remux failed: {(getattr(result, "stderr", None) or "")[:180]}')
        return False
    tmp.replace(path)
    return True


def fetch_video(
    url: str,
    *,
    http_fetch: Callable[..., bytes] | None = None,
    browser_fetch: Callable[[str], str] | None = None,
    ffmpeg: str | None = None,
    max_bytes: int | None = None,
) -> FetchedVideo:
    """Resolve an Instagram / Pinterest / direct URL to video bytes.
    `http_fetch(url, referer=, max_bytes=)`, `browser_fetch(url) -> html`
    and `ffmpeg` are injectable so tests never touch the network."""
    http_fetch = http_fetch or http_get
    max_bytes = max_bytes or config.PROMPT_REVERSE_MAX_VIDEO_MB * 1024 * 1024
    platform = detect_platform(url)
    if platform is None:
        raise ReverseError('that is not an Instagram reel, Pinterest pin or direct video link')
    if platform == 'direct':
        data = _download(url, referer=None, http_fetch=http_fetch, ffmpeg=ffmpeg, max_bytes=max_bytes)
        return FetchedVideo(data=data, media_url=url, platform=platform)

    page_url = canonical_url(url)
    candidates: list[str] = []
    try:
        candidates = extract_media_urls(http_fetch(page_url).decode('utf-8', errors='replace'))
    except Exception as exc:  # login walls, 4xx — the browser gets a turn
        logger.info('plain fetch of %s gave nothing usable: %s', page_url, exc)
    if not candidates and browser_fetch is not None:
        try:
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

            pool = ThreadPoolExecutor(max_workers=1)
            try:
                future = pool.submit(browser_fetch, page_url)
                try:
                    page_html = future.result(timeout=BROWSER_FETCH_HARD_TIMEOUT_S)
                except FuturesTimeout as exc:
                    raise ReverseError(
                        'Instagram / Pinterest page timed out — forward the video file here instead'
                    ) from exc
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
            candidates = extract_media_urls(page_html)
        except ReverseError:
            raise
        except Exception as exc:
            logger.warning('browser fetch of %s failed: %s', page_url, exc)
    if not candidates:
        raise ReverseError(
            f'could not find a video on that {platform} page (private, login-walled or not a video) — '
            'forward the video file here instead'
        )
    last_error: Exception | None = None
    for media_url in candidates[:5]:
        try:
            data = _download(media_url, referer=page_url, http_fetch=http_fetch, ffmpeg=ffmpeg, max_bytes=max_bytes)
            return FetchedVideo(data=data, media_url=media_url, platform=platform)
        except ReverseError as exc:
            if 'larger than' in str(exc):
                raise
            last_error = exc
        except Exception as exc:
            last_error = exc
    raise ReverseError(f'found the video link but could not download it ({last_error}) — forward the video file here instead')


def _download(media_url: str, *, referer: str | None, http_fetch, ffmpeg: str | None, max_bytes: int) -> bytes:
    if '.m3u8' in media_url.lower():
        if not ffmpeg:
            raise ReverseError('HLS playlist but no ffmpeg to stitch it')
        data = hls_to_mp4(media_url, referer=referer, ffmpeg=ffmpeg, max_bytes=max_bytes)
    else:
        data = http_fetch(media_url, referer=referer, max_bytes=max_bytes)
    if len(data) < MIN_VIDEO_BYTES or not looks_like_video(data):
        raise ReverseError('downloaded file is not a video')
    return data


# -------------------------------------------------------------- describe

DIMENSIONS = (
    'the product (exact type, material, finish, colour, size cues, branding surfaces — never a brand name)',
    'the environment / set (surfaces, backdrop, depth, time of day, weather, season)',
    'accessories and props (what surrounds the product and why it belongs)',
    'lighting (key / fill / rim direction, colour temperature, softness, practicals, reflections)',
    'camera (focal length, aperture / depth of field, angle, height, distance, lens character)',
    'motion (dolly, orbit, push, tilt, rack focus, speed ramps, slow motion fps, hand-held vs locked)',
    'textures and materials (how light plays on each surface: gloss, matte, grain, condensation, fabric)',
    'action (what physically happens — pours, drops, splashes, hands, unboxing, steam, particles)',
    'reveal strategy (how and when the product is shown: tease → partial → hero → end frame)',
    'emotion and tone (what the viewer should feel; pacing; sound design if audible)',
    'style vocabulary (cinematic realism, colour grade, film stock look, grain, vignette, "no text / no logo" rules)',
)

SYSTEM_INSTRUCTION = """You are a senior commercial director reverse-engineering a high-performing short product video into the exact generation prompt that would recreate it with an AI video model (Veo 3, Kling, Sora, Runway).

Watch the whole clip. Then write ONE prompt, segmented by real timestamps that cover the clip's full duration ({duration}) shot by shot, in the form "[0.0s–1.8s] …". Every segment must be specific and visual. Describe, in rich professional vocabulary, all of:
{dimensions}

Rules:
- Describe only what is visible or clearly implied; do not invent brand names, prices, claims or on-screen text that is not there.
- Never write marketing copy, hashtags or captions — this is a generation prompt.
- Use concrete numbers where a filmmaker would (focal length, fps, colour temperature, degrees of orbit, percent push-in).
- Keep every cut physically plausible and lighting continuous across cuts.
- Give extra attention to the first and last frame of every hard cut. Those instants become the recreate-reference images attached with this prompt. For each one, lock product pose and crop, glass / liquid / condensation, hand or prop, lighting direction and colour, camera height / lens / distance, and the set. Write the timestamped prompt so a video model hitting those exact frames would match them.
- End with a one-line "Style:" summary.
- HARD CAP: the `prompt` value MUST be strictly under 3000 characters including spaces. Think first — pick the shots and the densest words — then write. Full essence, no filler. Never pad toward 8k.
- The JSON object MUST be complete: close every string and the object. Never stop mid-sentence or mid-beat.
- Also list every hard cut / shot change as `cuts`. These are the frames a filmmaker needs to recreate the clip — not evenly spaced stills.

Quality bar — this exemplar shows the structure and vocabulary expected. Match its craft, not its length. Your prompt stays under 3000 characters including spaces; do not copy the exemplar's length:
---
{exemplar}
---

Return STRICT JSON with exactly three keys and nothing else:
{{"keyword": "<ONE uppercase word people would comment to get this prompt — the product category, e.g. SKINCARE, COFFEE, WATCH>", "prompt": "<the timestamped prompt as one string with newlines, strictly under 3000 characters>", "cuts": [{{"start": 0.0, "end": 1.8}}]}}
`cuts` covers the full duration in order. `start` / `end` are seconds at the first and last frame of that shot. Do not put the cuts array inside the prompt string."""

USER_PROMPT = (
    'Reverse-engineer this {duration} product video into the generation prompt described in your '
    'instructions. Think first, then write. Cover the full duration with timestamped segments. '
    'The prompt string MUST be strictly under 3000 characters including spaces. '
    'List every hard cut in `cuts`. '
    'Give extra attention to the start-frame and end-frame of each cut — those are the recreate-reference '
    'images. Return only complete JSON — close the prompt string, the cuts array and the object. Never stop mid-sentence.'
)

USER_PROMPT_RETRY = (
    'Your previous JSON was cut off mid-prompt. Return ONLY the complete JSON object '
    '{{"keyword":"<ONE uppercase word>","prompt":"<timestamped prompt under 3000 characters>",'
    '"cuts":[{{"start":0.0,"end":1.8}}]}} covering this {duration} clip. Close every string, '
    'the cuts array and the object. Do not stop mid-sentence. Stay strictly under 3000 characters including spaces.'
)

COMPRESS_USER = (
    'The prompt is {n} characters — too long. Think, then rewrite it STRICTLY UNDER 3000 '
    'characters including spaces. Keep every timestamp. Keep camera, product, action, emotion, '
    'world, and one Style: line. No filler. Return only complete JSON.'
)

REFINE_SYSTEM = """You are the same senior commercial director. You already watched the clip and drafted a timestamped prompt. Now you are also given the exact cut-reference JPEGs (labeled by timestamp) that will be attached when a human recreates this video.

Watch the clip again AND study every attached frame. Rewrite ONE generation prompt so each timestamped segment would produce a frame that matches the JPEG at that time — product pose, crop, lighting, camera, set, glass/liquid/hand. Do not mention JPEGs, "reference image", or the cuts array inside the prompt string.

HARD CAP: the `prompt` value MUST be strictly under 3000 characters including spaces. Think first, then write dense cinematic text.

Return STRICT JSON with exactly three keys:
{"keyword": "<ONE uppercase word>", "prompt": "<the rewritten timestamped prompt, under 3000 characters>", "cuts": [{"start": 0.0, "end": 1.8}]}
The JSON object MUST be complete. Never stop mid-sentence."""

REFINE_USER = (
    'These JPEG frames are the recreate-reference images for this {duration} clip:\n'
    '{frame_list}\n\n'
    'Draft prompt to rewrite (keep the timestamp structure, raise the match to these frames, '
    'stay strictly under 3000 characters including spaces):\n'
    '---\n{draft}\n---\n'
    'Watch the video and attend to the attached frames. Think, then return only complete JSON.'
)

ATTENTION_IMAGE_LIMIT = 10


def default_exemplar_path() -> Path:
    return Path(__file__).with_name('reverse_exemplar.txt')


def load_exemplar(path: str | Path | None = None) -> str:
    candidate = Path(path) if path else (Path(config.PROMPT_REVERSE_EXEMPLAR_PATH) if config.PROMPT_REVERSE_EXEMPLAR_PATH else default_exemplar_path())
    try:
        text = candidate.read_text(encoding='utf-8').strip()
    except OSError:
        text = ''
    if not text and candidate != default_exemplar_path():
        text = default_exemplar_path().read_text(encoding='utf-8').strip()
    return text


def _duration_label(duration_s: float | None) -> str:
    return f'{duration_s:.1f}-second' if duration_s and duration_s > 0 else 'short'


def resolve_vision_engine(raw: str | None) -> str:
    """gemini | astra | fable from a button payload or API field."""
    text = re.sub(r'[^a-z0-9]+', '', (raw or ENGINE_GEMINI).lower())
    aliases = {
        'gemini': ENGINE_GEMINI, 'google': ENGINE_GEMINI, 'flash': ENGINE_GEMINI,
        'astra': ENGINE_ASTRA, 'gpt6astra': ENGINE_ASTRA, 'gpt6': ENGINE_ASTRA,
        'openai': ENGINE_ASTRA, 'gpt': ENGINE_ASTRA,
        'fable': ENGINE_FABLE, 'claudefable5': ENGINE_FABLE, 'claudefable': ENGINE_FABLE,
        'claude': ENGINE_FABLE, 'anthropic': ENGINE_FABLE,
    }
    key = aliases.get(text, text)
    if key not in VISION_LABELS:
        raise ReverseError('unknown reverse model — pick Gemini, GPT-6 Astra or Claude Fable 5')
    return key


def vision_label(raw: str | None) -> str:
    try:
        return VISION_LABELS[resolve_vision_engine(raw)]
    except ReverseError:
        return VISION_LABELS[ENGINE_GEMINI]


def vision_api_model(raw: str | None) -> str:
    engine = resolve_vision_engine(raw)
    if engine == ENGINE_ASTRA:
        return getattr(config, 'PROMPT_REVERSE_ASTRA_MODEL', '') or 'gpt-6-astra'
    if engine == ENGINE_FABLE:
        return getattr(config, 'PROMPT_REVERSE_FABLE_MODEL', '') or 'claude-fable-5'
    return config.REPLICATE_VISION_MODEL


def vision_key_missing(raw: str | None) -> str | None:
    """Phone-readable reason if that engine cannot run, else None."""
    engine = resolve_vision_engine(raw)
    if engine == ENGINE_GEMINI and not getattr(config, 'REPLICATE_API_TOKEN', ''):
        return 'REPLICATE_API_TOKEN is missing in job_engine/.env — pick another model or add the key'
    if engine == ENGINE_ASTRA and not getattr(config, 'OPENAI_API_KEY', ''):
        return 'OPENAI_API_KEY is missing in job_engine/.env — pick another model or add the key'
    if engine == ENGINE_FABLE and not getattr(config, 'ANTHROPIC_API_KEY', ''):
        return 'ANTHROPIC_API_KEY is missing in job_engine/.env — pick another model or add the key'
    return None


def build_instruction(*, duration_s: float | None, exemplar: str | None = None) -> str:
    return SYSTEM_INSTRUCTION.format(
        duration=_duration_label(duration_s),
        dimensions='\n'.join(f'- {d}' for d in DIMENSIONS),
        exemplar=exemplar if exemplar is not None else load_exemplar(),
    )


def _strip_fences(text: str) -> str:
    text = (text or '').strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    return text.strip()


def clean_keyword(raw: str | None) -> str:
    word = re.sub(r'[^A-Za-z0-9 ]+', ' ', str(raw or '')).strip().split()
    if not word:
        return DEFAULT_KEYWORD
    return word[0].upper()[:18]


_JSON_ESCAPES = {
    '"': '"',
    '\\': '\\',
    '/': '/',
    'b': '\b',
    'f': '\f',
    'n': '\n',
    'r': '\r',
    't': '\t',
}


def _load_json_object(body: str) -> dict | None:
    try:
        data = json.loads(body)
        return data if isinstance(data, dict) else None
    except ValueError:
        pass
    match = re.search(r'\{.*\}', body, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def json_reading_complete(text: str) -> bool:
    """True only when the model closed a JSON object with a non-empty prompt."""
    data = _load_json_object(_strip_fences(text or ''))
    return bool(isinstance(data, dict) and str(data.get('prompt') or '').strip())


def _json_string_field(body: str, key: str) -> tuple[str | None, bool]:
    """Read a JSON string field even when the closing quote / brace is missing.

    Gemini sometimes emits a literal newline inside the prompt string (invalid
    JSON) or hits the token cap mid-value. Returns (value, closed).
    """
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"', body)
    if not match:
        return None, False
    i = match.end()
    out: list[str] = []
    while i < len(body):
        ch = body[i]
        if ch == '\\':
            if i + 1 >= len(body):
                return ''.join(out), False
            nxt = body[i + 1]
            if nxt == 'u' and i + 5 < len(body):
                hexpart = body[i + 2:i + 6]
                try:
                    out.append(chr(int(hexpart, 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            out.append(_JSON_ESCAPES.get(nxt, nxt))
            i += 2
            continue
        if ch == '"':
            return ''.join(out), True
        out.append(ch)
        i += 1
    value = ''.join(out).rstrip()
    return (value or None), False


SEGMENT_RE = re.compile(
    r'\[(\d+(?:\.\d+)?)\s*s?\s*[–\-\—to]+\s*(\d+(?:\.\d+)?)\s*s?\]',
    re.I,
)
REFERENCE_FRAME_COUNT = 14
CUT_END_INSET_S = 0.04


def _as_seconds(raw) -> float | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw or '').strip().lower().replace('seconds', '').replace('second', '').rstrip('s')
    try:
        return float(text)
    except ValueError:
        return None


def _cut_pair(item) -> tuple[float, float] | None:
    if isinstance(item, (int, float)) and not isinstance(item, bool):
        t = float(item)
        return (t, t)
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        start, end = _as_seconds(item[0]), _as_seconds(item[1])
        if start is None or end is None:
            return None
        return (start, end)
    if not isinstance(item, dict):
        return None
    start = _as_seconds(item.get('start') if item.get('start') is not None else item.get('from', item.get('t0', item.get('in'))))
    end = _as_seconds(item.get('end') if item.get('end') is not None else item.get('to', item.get('t1', item.get('out'))))
    if start is None and item.get('t') is not None:
        start = _as_seconds(item.get('t'))
        end = start
    if start is None or end is None:
        return None
    return (start, end)


def coerce_cuts(raw) -> list[tuple[float, float]]:
    """Accept cuts / timestamps in the shapes models actually emit."""
    if not raw:
        return []
    if isinstance(raw, dict):
        raw = raw.get('cuts') or raw.get('shots') or raw.get('frames') or raw.get('timestamps') or []
    if not isinstance(raw, (list, tuple)):
        return []
    if raw and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in raw):
        return [(float(t), float(t)) for t in raw]
    out: list[tuple[float, float]] = []
    for item in raw:
        pair = _cut_pair(item)
        if pair is not None:
            out.append(pair)
    return out


def cuts_from_prompt(prompt: str) -> list[tuple[float, float]]:
    """Shot ranges already written as `[0.0s–1.8s]` in the generation prompt."""
    pairs: list[tuple[float, float]] = []
    for match in SEGMENT_RE.finditer(prompt or ''):
        start, end = float(match.group(1)), float(match.group(2))
        if end < start:
            start, end = end, start
        pairs.append((start, end))
    return pairs


def extract_style_line(prompt: str) -> str:
    match = STYLE_LINE_RE.search(prompt or '')
    return match.group(1).strip() if match else ''


def _trim_words(text: str, limit: int) -> str:
    if limit <= 0:
        return ''
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(' ', 1)[0].rstrip(' ,;:.-')
    return cut or text[:limit]


def _split_prompt_parts(prompt: str) -> tuple[list[str], str]:
    """Timestamped blocks plus a trailing Style: line."""
    text = (prompt or '').strip()
    style = extract_style_line(text)
    body = text
    if style:
        match = STYLE_LINE_RE.search(text)
        if match:
            body = text[:match.start()].strip()
    matches = list(SEGMENT_RE.finditer(body))
    if not matches:
        return ([body] if body else [], style)
    parts: list[str] = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        parts.append(body[match.start():end].strip())
    return parts, style


def fit_prompt(prompt: str, limit: int = PROMPT_MAX_CHARS) -> str:
    """Hard cap including spaces. Keep every timestamp and the Style lock.

    Ashok: strictly under 3000 characters — default limit is 2999.
    """
    text = re.sub(r'\n{3,}', '\n\n', (prompt or '').strip())
    if len(text) <= limit:
        return text
    parts, style = _split_prompt_parts(text)
    style_line = style if style else ''
    if style_line and not style_line.lower().startswith('style:'):
        style_line = f'Style: {style_line}'
    style_cost = (1 + len(style_line)) if style_line else 0
    budget = max(80, limit - style_cost)

    def total() -> int:
        if not parts:
            return 0
        return sum(len(p) for p in parts) + (len(parts) - 1)

    for _ in range(64):
        if total() <= budget:
            break
        idx = max(range(len(parts)), key=lambda i: len(parts[i]))
        longest = parts[idx]
        header = SEGMENT_RE.match(longest)
        floor = len(header.group(0)) + 1 if header else 24
        if len(longest) <= floor:
            break
        need = total() - budget
        parts[idx] = _trim_words(longest, max(floor, len(longest) - max(need, 16)))
    out = '\n'.join(p for p in parts if p)
    if style_line:
        if len(out) + 1 + len(style_line) <= limit:
            out = f'{out}\n{style_line}' if out else style_line
        else:
            out = _trim_words(out, max(0, limit - len(style_line) - 1))
            out = f'{out}\n{style_line}'.strip()
    if len(out) > limit:
        out = _trim_words(out, limit)
    return out


def apply_prompt_cap(reading: ReverseReading) -> ReverseReading:
    """Last door: stored prompt is strictly under 3000 characters."""
    reading.prompt = fit_prompt(reading.prompt or '')
    return reading


def normalize_cuts(cuts: list[tuple[float, float]], duration_s: float | None) -> list[tuple[float, float]]:
    limit = duration_s if duration_s and duration_s > 0 else None
    cleaned: list[tuple[float, float]] = []
    for start, end in cuts:
        if start < 0:
            start = 0.0
        if end < 0:
            end = 0.0
        if end < start:
            start, end = end, start
        if limit is not None:
            start = min(start, limit)
            end = min(end, limit)
        if cleaned and abs(start - cleaned[-1][0]) < 0.02 and abs(end - cleaned[-1][1]) < 0.02:
            continue
        cleaned.append((start, end))
    return cleaned


def _shot_ranges(cuts: list[tuple[float, float]], duration_s: float | None) -> list[tuple[float, float]]:
    """Point timestamps become shot ranges between consecutive cuts."""
    ranges = normalize_cuts(cuts, duration_s)
    if not ranges:
        end = duration_s if duration_s and duration_s > 0 else 0.0
        return [(0.0, end)]
    if all(abs(end - start) < 0.05 for start, end in ranges):
        stamps = sorted({round(start, 3) for start, _end in ranges})
        end = duration_s if duration_s and duration_s > 0 else stamps[-1]
        if stamps[-1] < end - 0.05:
            stamps.append(round(end, 3))
        if len(stamps) == 1:
            return [(stamps[0], end)]
        return [(stamps[i], stamps[i + 1]) for i in range(len(stamps) - 1)]
    return ranges


def plan_reference_times(
    cuts: list[tuple[float, float]],
    *,
    duration_s: float | None,
    count: int = REFERENCE_FRAME_COUNT,
) -> list[float]:
    """14 timestamps from hard cuts — start + end of each shot.

    Not an equal grid. Extra slots go into the longest shots (or the
    largest gaps when the model only gave point timestamps). Surplus
    short cuts are dropped; the first start and last end stay.
    """
    count = max(2, int(count or REFERENCE_FRAME_COUNT))
    ranges = _shot_ranges(cuts, duration_s)

    def _end_in_shot(start: float, end: float) -> float:
        if end - start > CUT_END_INSET_S * 2:
            return end - CUT_END_INSET_S
        return end if end > start else start

    def _dedupe(values: list[float]) -> list[float]:
        kept: list[float] = []
        for t in values:
            t = max(0.0, float(t))
            if duration_s and duration_s > 0:
                t = min(t, duration_s)
            if kept and abs(t - kept[-1]) < 0.02:
                continue
            kept.append(round(t, 3))
        return kept

    points: list[float] = []
    for start, end in ranges:
        points.append(start)
        points.append(_end_in_shot(start, end))
    points[0] = ranges[0][0]
    points[-1] = _end_in_shot(*ranges[-1])
    must = {round(ranges[0][0], 3), round(_end_in_shot(*ranges[-1]), 3)}
    points = _dedupe(points)

    if len(points) > count:
        ranked = sorted(ranges, key=lambda pair: pair[1] - pair[0], reverse=True)
        keep: list[float] = [ranges[0][0], _end_in_shot(*ranges[-1])]
        for start, end in ranked:
            if len(_dedupe(sorted(keep))) >= count:
                break
            keep.append(start)
            keep.append(_end_in_shot(start, end))
        points = _dedupe(sorted(keep))[:count]
        for required in must:
            if required not in points and len(points) == count:
                points[-2] = required
                points = _dedupe(sorted(points))[:count]
    elif len(points) < count:
        extras: list[float] = []
        for frac in (0.35, 0.7, 0.2, 0.85, 0.5):
            for start, end in sorted(ranges, key=lambda pair: pair[1] - pair[0], reverse=True):
                span = end - start
                if span < 0.15:
                    continue
                extras.append(start + span * frac)
            merged = _dedupe(sorted(points + extras))
            if len(merged) >= count:
                points = merged[:count]
                break
        else:
            points = _dedupe(sorted(points + extras))
        # Largest remaining gap (still inside a cut / between named times)
        while len(points) < count:
            seq = list(points)
            if duration_s and duration_s > points[-1] + 0.08:
                seq.append(duration_s)
            best_i, best_gap = -1, 0.0
            for i in range(len(seq) - 1):
                gap = seq[i + 1] - seq[i]
                if gap > best_gap:
                    best_gap, best_i = gap, i
            if best_i < 0 or best_gap < 0.12:
                break
            points = _dedupe(sorted(points + [(seq[best_i] + seq[best_i + 1]) / 2]))
    return points[:count]


def parse_reading(text: str, *, model: str = '') -> ReverseReading:
    """The model is asked for JSON; tolerate fences, prose around it, a
    truncated JSON object, or a bare prompt (keyword falls back to PRODUCT).

    Never store the `{ "keyword": …, "prompt": … }` wrapper as the prompt —
    that is what reverse #7 scrolled in the reel and pasted in Telegram.
    The `cuts` / `frames` array is stripped here and never enters prompt_text.
    """
    raw = (text or '').strip()
    body = _strip_fences(raw)
    data = _load_json_object(body)
    if isinstance(data, dict) and str(data.get('prompt') or '').strip():
        prompt = str(data['prompt']).strip()
        cuts = coerce_cuts(data.get('cuts') or data.get('shots') or data.get('frames') or data.get('timestamps')) or cuts_from_prompt(prompt)
        return ReverseReading(
            keyword=clean_keyword(data.get('keyword')),
            prompt=prompt,
            model=model,
            raw=raw,
            cuts=cuts,
        )
    keyword_raw, _closed = _json_string_field(body, 'keyword')
    prompt_val, _prompt_closed = _json_string_field(body, 'prompt')
    if prompt_val and prompt_val.strip():
        prompt = prompt_val.strip()
        return ReverseReading(
            keyword=clean_keyword(keyword_raw),
            prompt=prompt,
            model=model,
            raw=raw,
            cuts=cuts_from_prompt(prompt),
        )
    if len(body) < 80:
        raise ReverseError(f'vision model returned no prompt: {body[:120] or "(empty)"}')
    if body.lstrip().startswith('{') and '"prompt"' in body:
        raise ReverseError('vision model returned truncated JSON with no recoverable prompt')
    return ReverseReading(keyword=DEFAULT_KEYWORD, prompt=body, model=model, raw=raw, cuts=cuts_from_prompt(body))


def frame_jpeg_at(
    video_path: Path,
    t: float,
    *,
    ffmpeg: str | None = None,
) -> bytes:
    """One JPEG at timestamp `t` from the downloaded clip (ffmpeg seek)."""
    from app.prompts import post_reel

    exe = ffmpeg or post_reel.ffmpeg_exe()
    cmd = [
        exe, '-v', 'error', '-ss', f'{max(0.0, t):.3f}', '-i', str(video_path),
        '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'mjpeg', '-q:v', '3', '-',
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    if result.returncode != 0 or len(result.stdout) < 64:
        err = (result.stderr or b'').decode('utf-8', errors='replace').strip()[:160]
        raise ReverseError(f'could not grab frame at {t:.2f}s: {err or "empty jpeg"}')
    return result.stdout


def store_reference_frames(
    video_path: Path,
    times: list[float],
    *,
    prompt_id: int,
    grab: Callable[..., bytes] | None = None,
    store: Callable[..., Path] | None = None,
    key_for: Callable[..., str] | None = None,
    ffmpeg: str | None = None,
) -> list[ReferenceFrame]:
    """Write one JPEG per cut timestamp next to the source clip."""
    from app.prompts import video_creator

    grab = grab or (lambda path, t, **_kw: frame_jpeg_at(path, t, ffmpeg=ffmpeg))
    store = store or video_creator.store_bytes
    key_for = key_for or video_creator.asset_key
    frames: list[ReferenceFrame] = []
    for index, t in enumerate(times, start=1):
        data = b''
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                data = grab(video_path, t)
                if data:
                    break
            except Exception as exc:
                last_exc = exc
                logger.warning('reference frame %s at %.3fs try %s failed: %s', index, t, attempt + 1, exc)
        if not data:
            if last_exc:
                logger.warning('reference frame %s at %.3fs skipped: %s', index, t, last_exc)
            continue
        if not data:
            continue
        key = key_for(f'rref{index:02d}', prompt_id=prompt_id, suffix='jpg')
        store(key, data, content_type='image/jpeg')
        frames.append(ReferenceFrame(
            t=round(float(t), 3),
            key=key,
            filename=f'cut-{index:02d}-{t:.2f}s.jpg',
        ))
    return frames


def serialize_reference_frames(frames: list[ReferenceFrame]) -> list[dict]:
    return [{'t': frame.t, 'key': frame.key, 'filename': frame.filename} for frame in frames]


def load_reference_frames(raw) -> list[dict]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict) and item.get('key')]
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except ValueError:
            return []
        return load_reference_frames(data)
    return []


def jpeg_data_uri(blob: bytes) -> str:
    return f'data:image/jpeg;base64,{base64.standard_b64encode(blob).decode("ascii")}'


def pick_attention_frames(
    frames: list[ReferenceFrame],
    limit: int = ATTENTION_IMAGE_LIMIT,
) -> list[ReferenceFrame]:
    """Gemini accepts at most 10 images. Keep first + last cut frames and
    spread the rest — never drop the clip's opening or closing still."""
    ordered = sorted(frames, key=lambda f: (f.t, f.filename or '', f.key))
    n = len(ordered)
    if n <= limit:
        return list(ordered)
    if limit <= 1:
        return [ordered[0]]
    indexes = {0, n - 1}
    if limit > 2:
        for i in range(1, limit - 1):
            indexes.add(round(i * (n - 1) / (limit - 1)))
    idx = 1
    while len(indexes) < limit and idx < n - 1:
        indexes.add(idx)
        idx += 1
    return [ordered[i] for i in sorted(indexes)][:limit]


def read_reference_jpeg(key: str, *, read_asset=None) -> bytes | None:
    if read_asset is not None:
        rec = read_asset(key)
        if rec is None:
            return None
        if isinstance(rec, (bytes, bytearray)):
            blob = bytes(rec)
        elif isinstance(rec, dict):
            blob = rec.get('data') or b''
            if isinstance(blob, str):
                blob = blob.encode('latin-1')
        else:
            return None
        return blob if len(blob) >= 8 else None
    from app.prompts import video_creator

    path = video_creator.assets_root() / key
    try:
        blob = path.read_bytes()
    except OSError:
        return None
    return blob if len(blob) >= 8 else None


def load_reference_jpegs(
    frames: list[ReferenceFrame],
    *,
    read_asset=None,
) -> list[tuple[ReferenceFrame, bytes]]:
    out: list[tuple[ReferenceFrame, bytes]] = []
    for frame in pick_attention_frames(frames):
        blob = read_reference_jpeg(frame.key, read_asset=read_asset)
        if blob:
            out.append((frame, blob))
    return out


def refine_prompt_with_frames(
    video_path: Path,
    *,
    prompt: str,
    frames: list[ReferenceFrame],
    duration_s: float | None,
    engine: str | None = ENGINE_GEMINI,
    keyword: str | None = None,
    public_url: str | None = None,
    run: Callable[..., object] | None = None,
    complete: Callable[..., str] | None = None,
    read_asset=None,
    log: Callable[[str], None] | None = None,
) -> ReverseReading | None:
    """Second pass: watch the clip again with the cut-reference JPEGs.

    First pass stays video-only (Ashok rejected stills-as-the-reverse).
    These JPEGs are extra attention so each timestamp matches the frame
    a human will attach when recreating the clip. Failure or a much
    shorter rewrite keeps the draft. Frames are not re-extracted.
    """
    draft = (prompt or '').strip()
    if not draft or not frames:
        return None
    loaded = load_reference_jpegs(frames, read_asset=read_asset)
    if not loaded:
        return None
    labels = '\n'.join(
        f'- {frame.filename or f"{frame.t:.2f}s"} at {frame.t:.2f}s'
        for frame, _ in loaded
    )
    user = (
        REFINE_USER
        .replace('{duration}', _duration_label(duration_s))
        .replace('{frame_list}', labels)
        .replace('{draft}', draft)
    )
    images = [jpeg_data_uri(blob) for _, blob in loaded]
    engine_key = resolve_vision_engine(engine)
    if log:
        log(f'{vision_label(engine_key)} attending to {len(images)} cut-reference frames')
    try:
        if engine_key == ENGINE_GEMINI:
            reading = _describe_gemini(
                video_path,
                duration_s=duration_s,
                run=run,
                log=log,
                exemplar='',
                public_url=public_url,
                _attempt=0,
                system_instruction=REFINE_SYSTEM,
                user_prompt=user,
                images=images,
            )
        else:
            model = vision_api_model(engine_key)
            complete_fn = complete
            if complete_fn is None:
                missing = vision_key_missing(engine_key)
                if missing:
                    logger.warning('Cut-frame prompt refine skipped: %s', missing)
                    return None
                complete_fn = _openai_complete if engine_key == ENGINE_ASTRA else _anthropic_complete
            text = complete_fn(
                model=model,
                system=REFINE_SYSTEM,
                user_text=user + '\n' + VIDEO_FILE_NOTE,
                video_path=video_path,
                public_url=public_url,
                images=images,
            )
            reading = parse_reading(text, model=model)
    except Exception as exc:
        logger.warning('Cut-frame prompt refine failed: %s', exc)
        return None
    reading = apply_prompt_cap(reading)
    refined = (reading.prompt or '').strip()
    if not refined or len(refined) < max(80, min(int(len(draft) * 0.55), PROMPT_MAX_CHARS // 2)):
        logger.warning('Cut-frame prompt refine discarded (empty or too short)')
        return None
    if keyword and (not reading.keyword or reading.keyword == DEFAULT_KEYWORD):
        reading.keyword = clean_keyword(keyword)
    return reading


def _output_text(output) -> str:
    if output is None:
        return ''
    if isinstance(output, (list, tuple)):
        return ''.join(str(part) for part in output)
    if hasattr(output, 'read'):
        return output.read().decode('utf-8', errors='replace')
    return str(output)


def mime_for_video(path: Path | str) -> str:
    """Gemini requires an explicit mime; never application/octet-stream."""
    ext = Path(path).suffix.lower()
    return VIDEO_MIME.get(ext, 'video/mp4')


def video_input_for_vision(path: Path, *, public_url: str | None = None) -> str:
    """What Gemini-on-Replicate receives as `videos[0]`.

    A raw file handle is uploaded to Replicate's Files API; that URL has
    no extension. The Cog then hands Google a nameless file and Google
    raises: "Unknown mime type… please set the `mime_type` argument"
    (reverse #1, 2026-09-10). So we never pass a handle.

    Prefer our public ``.mp4`` asset URL whenever we have one — Replicate
    fetches it, ``predictions.create`` is a tiny JSON POST, and a Gemini
    row appears immediately. A multi-MB data-URI (reverse #14 / #16) either
    hangs the upload or dies inside Google as E001.

    Data-URI is the fallback when there is no public ``.mp4`` (tests,
    missing partner URL) or when Replicate cannot fetch our URL.
    """
    url = (public_url or '').strip()
    if (
        url.lower().startswith(('http://', 'https://'))
        and DIRECT_RE.search(url.split('#', 1)[0])
    ):
        return url
    data = path.read_bytes()
    mime = mime_for_video(path)
    return f'data:{mime};base64,{base64.standard_b64encode(data).decode("ascii")}'


VIDEO_FILE_NOTE = (
    'The source clip is attached as a video file. Watch the whole file. '
    'Do not invent shots you cannot see. If you cannot view it natively, '
    'use your python/code tool on the attached mp4 (ffprobe, opencv, ffmpeg) '
    'and then return the JSON.'
)


def describe_video(
    video_path: Path,
    *,
    duration_s: float | None,
    engine: str | None = ENGINE_GEMINI,
    run: Callable[..., object] | None = None,
    complete: Callable[..., str] | None = None,
    log: Callable[[str], None] | None = None,
    exemplar: str | None = None,
    public_url: str | None = None,
    _attempt: int = 0,
) -> ReverseReading:
    """Watch the clip and return keyword + timestamped prompt.

    Every engine gets the video file — Gemini natively, Astra/Fable as the
    mp4 (native video block if the API accepts it, otherwise the file in
    their code sandbox, the way Codex hands Astra a clip). `run` /
    `complete` are injectable for tests. Never extract stills ourselves
    for this first pass — cut JPEGs are a second `refine_prompt_with_frames`
    call after the frames exist.
    """
    engine_key = resolve_vision_engine(engine)
    if engine_key == ENGINE_GEMINI:
        return _describe_gemini(
            video_path,
            duration_s=duration_s,
            run=run,
            log=log,
            exemplar=exemplar,
            public_url=public_url,
            _attempt=_attempt,
        )
    return _describe_file(
        video_path,
        duration_s=duration_s,
        engine=engine_key,
        complete=complete,
        log=log,
        exemplar=exemplar,
        public_url=public_url,
        _attempt=_attempt,
    )


def _describe_gemini(
    video_path: Path,
    *,
    duration_s: float | None,
    run: Callable[..., object] | None,
    log: Callable[[str], None] | None,
    exemplar: str | None,
    public_url: str | None,
    _attempt: int,
    system_instruction: str | None = None,
    user_prompt: str | None = None,
    images: list[str] | None = None,
) -> ReverseReading:
    """Gemini (Replicate) watches the clip. Thinking is on (8k) so it can
    plan a prompt strictly under 3000 characters. 32k output leaves room
    for thinking + JSON. If the first JSON still does not close, one retry.
    Optional `images` is the second-pass cut-reference JPEGs only.
    """
    model = vision_api_model(ENGINE_GEMINI)
    if run is None:
        missing = vision_key_missing(ENGINE_GEMINI)
        if missing:
            raise ReverseError(missing)
        import replicate

        from app.prompts.video_creator import replicate_render

        client = replicate.Client(api_token=config.REPLICATE_API_TOKEN)

        def run(model, input):  # noqa: A001
            return replicate_render(client, model, input=input, budget_s=DESCRIBE_BUDGET_S, log=log)

    prompt_tmpl = USER_PROMPT_RETRY if _attempt else USER_PROMPT
    video = video_input_for_vision(video_path, public_url=public_url)
    inputs = {
        'prompt': user_prompt or prompt_tmpl.format(duration=_duration_label(duration_s)),
        'videos': [video],
        'system_instruction': system_instruction or build_instruction(duration_s=duration_s, exemplar=exemplar),
        'temperature': 0.7,
        'max_output_tokens': MAX_OUTPUT_TOKENS,
        'thinking_budget': THINKING_BUDGET,
    }
    if images:
        inputs['images'] = list(images)[:ATTENTION_IMAGE_LIMIT]
    if log:
        if isinstance(video, str) and video.startswith('data:'):
            log(f'Gemini payload: data-URI {len(video) // 1024} KB (no public .mp4 URL)')
        else:
            log(f'Gemini payload: {video}')
    try:
        output = run(model, input=inputs)
    except Exception as exc:
        output = _retry_gemini_video(
            exc,
            video=video,
            video_path=video_path,
            inputs=inputs,
            run=run,
            model=model,
            log=log,
        )
    text = _output_text(output)
    reading = parse_reading(text, model=model)
    if _attempt == 0 and not json_reading_complete(text):
        if log:
            log('vision JSON was truncated — asking once more for the complete object')
        retry = _describe_gemini(
            video_path,
            duration_s=duration_s,
            run=run,
            log=log,
            exemplar=exemplar,
            public_url=public_url,
            _attempt=1,
            system_instruction=system_instruction,
            user_prompt=user_prompt,
            images=images,
        )
        if json_reading_complete(retry.raw) or len(retry.prompt) > len(reading.prompt):
            reading = retry
    return _maybe_compress_reading(reading, inputs=inputs, run=run, model=model, log=log)


def _maybe_compress_reading(
    reading: ReverseReading,
    *,
    inputs: dict,
    run,
    model: str,
    log: Callable[[str], None] | None,
) -> ReverseReading:
    """If Gemini wrote past the 3000-char door, think once more and fit."""
    prompt = (reading.prompt or '').strip()
    if len(prompt) < PROMPT_CHAR_LIMIT:
        return apply_prompt_cap(reading)
    if log:
        log(f'prompt {len(prompt)} chars — thinking compress to under {PROMPT_CHAR_LIMIT}')
    compress = dict(inputs)
    compress['prompt'] = COMPRESS_USER.format(n=len(prompt))
    try:
        compressed = parse_reading(_output_text(run(model, input=compress)), model=model)
        if compressed.prompt and len(compressed.prompt) < len(prompt):
            reading = compressed
    except Exception as exc:
        logger.warning('prompt compress retry failed: %s', exc)
    return apply_prompt_cap(reading)


def _describe_file(
    video_path: Path,
    *,
    duration_s: float | None,
    engine: str,
    complete: Callable[..., str] | None,
    log: Callable[[str], None] | None,
    exemplar: str | None,
    public_url: str | None,
    _attempt: int,
) -> ReverseReading:
    """GPT-6 Astra and Claude Fable 5 get the mp4 file, not JPEGs we sampled."""
    model = vision_api_model(engine)
    prompt_tmpl = USER_PROMPT_RETRY if _attempt else USER_PROMPT
    user_text = prompt_tmpl.format(duration=_duration_label(duration_s)) + '\n' + VIDEO_FILE_NOTE
    system = build_instruction(duration_s=duration_s, exemplar=exemplar)
    if complete is None:
        missing = vision_key_missing(engine)
        if missing:
            raise ReverseError(missing)
        complete = _openai_complete if engine == ENGINE_ASTRA else _anthropic_complete
    if log:
        log(f'{vision_label(engine)} reading the video file ({model})')
    text = complete(
        model=model,
        system=system,
        user_text=user_text,
        video_path=video_path,
        public_url=public_url,
    )
    reading = parse_reading(text, model=model)
    if _attempt == 0 and not json_reading_complete(text):
        if log:
            log('vision JSON was truncated — asking once more for the complete object')
        retry = _describe_file(
            video_path,
            duration_s=duration_s,
            engine=engine,
            complete=complete,
            log=log,
            exemplar=exemplar,
            public_url=public_url,
            _attempt=1,
        )
        if json_reading_complete(retry.raw) or len(retry.prompt) > len(reading.prompt):
            reading = retry
    prompt = (reading.prompt or '').strip()
    if len(prompt) >= PROMPT_CHAR_LIMIT:
        if log:
            log(f'prompt {len(prompt)} chars — thinking compress to under {PROMPT_CHAR_LIMIT}')
        try:
            text = complete(
                model=model,
                system=system,
                user_text=COMPRESS_USER.format(n=len(prompt)) + '\n' + VIDEO_FILE_NOTE,
                video_path=video_path,
                public_url=public_url,
            )
            compressed = parse_reading(text, model=model)
            if compressed.prompt and len(compressed.prompt) < len(prompt):
                reading = compressed
        except Exception as exc:
            logger.warning('prompt compress retry failed: %s', exc)
    return apply_prompt_cap(reading)


def _gemini_cannot_read(exc: BaseException) -> bool:
    """Google E001 / decode failures — the clip reached Gemini but it refused."""
    text = str(exc).lower()
    return any(token in text for token in (
        'e001', 'could not process', 'failed to process', 'unable to process',
        'invalid video', 'unsupported video', 'could not retrieve',
        'failed to load', 'unknown mime', 'not a valid video',
    ))


def _public_video_fetch_failed(exc: BaseException) -> bool:
    """Replicate/Gemini could not pull our public .mp4 — try a data-URI."""
    text = str(exc).lower()
    markers = (
        'fetch', 'download', '404', '403', '401', 'timed out', 'timeout',
        'unreachable', 'could not retrieve', 'failed to load', 'http 5',
        'mime', 'unknown mime', 'content type',
    )
    return any(token in text for token in markers)


def _human_gemini_error(exc: BaseException) -> str:
    text = str(exc)
    low = text.lower()
    if 'e001' in low:
        return (
            'Gemini could not read this clip (E001). '
            'Pinterest/HLS files often need an H.264 remux — tap Retry, '
            'or forward the video file and pick Gemini again. Astra/Fable also work.'
        )
    if 'create still uploading' in low:
        return (
            'Gemini never got the clip — the upload hung. '
            'Tap Retry (public .mp4 URL) or forward the file.'
        )
    return f'Gemini failed: {text[:400]}'


def _retry_gemini_video(
    exc: BaseException,
    *,
    video: str,
    video_path: Path,
    inputs: dict,
    run,
    model: str,
    log: Callable[[str], None] | None,
):
    """One retry: remux if E001, then send a data-URI if the public URL failed."""
    url_first = isinstance(video, str) and video.startswith('http')
    should = _gemini_cannot_read(exc) or (url_first and _public_video_fetch_failed(exc))
    if not should:
        raise ReverseError(_human_gemini_error(exc)) from exc
    if log:
        log(f'Gemini refused the first payload ({exc}) — remux + data-URI retry')
    try:
        prepare_vision_clip(video_path, force=_gemini_cannot_read(exc), log=log)
    except Exception as remux_exc:
        if log:
            log(f'Gemini remux skipped: {remux_exc}')
    fallback = dict(inputs)
    fallback['videos'] = [video_input_for_vision(video_path, public_url=None)]
    try:
        return run(model, input=fallback)
    except Exception as exc2:
        raise ReverseError(_human_gemini_error(exc2)) from exc2


def _retryable_video_error(exc: BaseException) -> bool:
    """True when this API shape refused the mp4 — try the next shape."""
    status = getattr(exc, 'status_code', None)
    if status is None:
        response = getattr(exc, 'response', None)
        status = getattr(response, 'status_code', None)
    if status in (401, 403, 429):
        return False
    text = str(exc).lower()
    markers = (
        'invalid', 'unsupported', 'unknown', 'not supported', 'unrecognized',
        'invalid_request', 'could not parse', 'unexpected', 'mime',
        'content type', 'input_video', 'video_url', 'file_data', 'file_url',
        'does not support', 'not a valid', 'unprocessable',
    )
    if any(token in text for token in markers):
        return True
    return status in (400, 404, 415, 422)


def _public_mp4_url(public_url: str | None) -> str | None:
    url = (public_url or '').strip()
    if url.lower().startswith(('http://', 'https://')) and DIRECT_RE.search(url.split('#', 1)[0]):
        return url
    return None


def astra_content_attempts(path: Path, *, public_url: str | None, user_text: str) -> list[tuple[str, list[dict]]]:
    """Named user-content shapes that send the mp4. Never JPEGs we extracted."""
    filename = path.name if path.suffix else 'clip.mp4'
    attempts: list[tuple[str, list[dict]]] = []
    public = _public_mp4_url(public_url)
    if public:
        attempts.append(('input_video_url', [
            {'type': 'input_video', 'video_url': public},
            {'type': 'input_text', 'text': user_text},
        ]))
        attempts.append(('input_file_url', [
            {'type': 'input_file', 'filename': filename, 'file_url': public},
            {'type': 'input_text', 'text': user_text},
        ]))
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if size <= DATA_URI_MAX_BYTES:
        uri = video_input_for_vision(path, public_url=None)
        attempts.append(('input_video', [
            {'type': 'input_video', 'video_url': uri},
            {'type': 'input_text', 'text': user_text},
        ]))
        attempts.append(('input_file', [
            {'type': 'input_file', 'filename': filename, 'file_data': uri},
            {'type': 'input_text', 'text': user_text},
        ]))
    return attempts


def fable_content_attempts(path: Path, *, public_url: str | None, user_text: str) -> list[tuple[str, list[dict]]]:
    """Named Claude content shapes that send the mp4. Never JPEGs we extracted."""
    mime = mime_for_video(path)
    attempts: list[tuple[str, list[dict]]] = []
    public = _public_mp4_url(public_url)
    if public:
        attempts.append(('video_url', [
            {'type': 'video', 'source': {'type': 'url', 'url': public}},
            {'type': 'text', 'text': user_text},
        ]))
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if size <= DATA_URI_MAX_BYTES:
        uri = video_input_for_vision(path, public_url=None)
        raw = uri.split(',', 1)[-1]
        attempts.append(('video_base64', [
            {
                'type': 'video',
                'source': {'type': 'base64', 'media_type': mime, 'data': raw},
            },
            {'type': 'text', 'text': user_text},
        ]))
    return attempts


def _response_output_text(response) -> str:
    text = (getattr(response, 'output_text', None) or '').strip()
    if text:
        return text
    parts: list[str] = []
    for item in getattr(response, 'output', None) or []:
        for block in getattr(item, 'content', None) or []:
            if getattr(block, 'text', None):
                parts.append(block.text)
            elif isinstance(block, dict) and block.get('text'):
                parts.append(str(block['text']))
    return '\n'.join(parts).strip()


def _openai_upload_video(client, path: Path) -> str:
    mime = mime_for_video(path)
    filename = path.name or 'clip.mp4'
    with path.open('rb') as handle:
        kwargs = {'file': (filename, handle, mime), 'purpose': 'user_data'}
        try:
            uploaded = client.files.create(
                **kwargs,
                expires_after={'anchor': 'created_at', 'seconds': 3600},
            )
        except TypeError:
            handle.seek(0)
            uploaded = client.files.create(file=(filename, handle, mime), purpose='user_data')
    file_id = getattr(uploaded, 'id', None) or (uploaded.get('id') if isinstance(uploaded, dict) else None)
    if not file_id:
        raise ReverseError('OpenAI Files API returned no file id for the video')
    return str(file_id)


def _astra_image_blocks(images: list[str] | None) -> list[dict]:
    return [{'type': 'input_image', 'image_url': uri} for uri in (images or []) if uri]


def _fable_image_blocks(images: list[str] | None) -> list[dict]:
    blocks: list[dict] = []
    for uri in images or []:
        if not uri:
            continue
        raw = uri.split(',', 1)[-1]
        media = 'image/jpeg'
        if uri.startswith('data:') and ';base64,' in uri:
            media = uri.split(';', 1)[0].split(':', 1)[-1] or media
        blocks.append({
            'type': 'image',
            'source': {'type': 'base64', 'media_type': media, 'data': raw},
        })
    return blocks


def _openai_complete(
    *,
    model: str,
    system: str,
    user_text: str,
    video_path: Path,
    public_url: str | None = None,
    client=None,
    images: list[str] | None = None,
) -> str:
    """Send Astra the mp4. Codex-equivalent: file in a code-interpreter sandbox.
    Optional `images` are second-pass cut-reference JPEGs — never a stills-only reverse.
    """
    from openai import OpenAI

    if client is None:
        client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=DESCRIBE_BUDGET_S)
    path = Path(video_path)
    extra = _astra_image_blocks(images)
    last_error: BaseException | None = None
    for label, content in astra_content_attempts(path, public_url=public_url, user_text=user_text):
        try:
            response = client.responses.create(
                model=model,
                instructions=system,
                input=[{'role': 'user', 'content': list(content) + extra}],
                max_output_tokens=MAX_OUTPUT_TOKENS,
            )
            text = _response_output_text(response)
            if text:
                return text
            last_error = ReverseError(f'{model} returned an empty reverse prompt ({label})')
        except Exception as exc:
            last_error = exc
            if not _retryable_video_error(exc):
                raise ReverseError(f'{model} refused the video file: {exc}') from exc
            logger.warning('Astra %s path failed: %s', label, exc)

    file_id = None
    try:
        file_id = _openai_upload_video(client, path)
        response = client.responses.create(
            model=model,
            instructions=system,
            input=[{
                'role': 'user',
                'content': [
                    {'type': 'input_file', 'file_id': file_id},
                    {'type': 'input_text', 'text': user_text},
                    *extra,
                ],
            }],
            tools=[{
                'type': 'code_interpreter',
                'container': {
                    'type': 'auto',
                    'memory_limit': '4g',
                    'file_ids': [file_id],
                },
            }],
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
        text = _response_output_text(response)
        if text:
            return text
        raise ReverseError(f'{model} returned an empty reverse prompt (code_interpreter)')
    except ReverseError:
        raise
    except Exception as exc:
        last_error = exc
        raise ReverseError(f'{model} could not read the video file ({last_error})') from exc
    finally:
        if file_id:
            try:
                client.files.delete(file_id)
            except Exception:
                logger.debug('could not delete OpenAI file %s', file_id)


def _message_text(message) -> str:
    parts: list[str] = []
    for block in getattr(message, 'content', None) or []:
        btype = getattr(block, 'type', None)
        if btype is None and isinstance(block, dict):
            btype = block.get('type')
        if btype != 'text':
            continue
        text = getattr(block, 'text', None)
        if text is None and isinstance(block, dict):
            text = block.get('text')
        if text:
            parts.append(str(text))
    return '\n'.join(parts).strip()


def _anthropic_upload_video(client, path: Path) -> str:
    mime = mime_for_video(path)
    filename = path.name or 'clip.mp4'
    files_api = getattr(client, 'files', None) or getattr(getattr(client, 'beta', None), 'files', None)
    if files_api is None:
        raise ReverseError('Anthropic SDK has no files.upload — upgrade anthropic')
    with path.open('rb') as handle:
        uploaded = files_api.upload(file=(filename, handle, mime))
    file_id = getattr(uploaded, 'id', None) or (uploaded.get('id') if isinstance(uploaded, dict) else None)
    if not file_id:
        raise ReverseError('Anthropic Files API returned no file id for the video')
    return str(file_id)


def _anthropic_complete(
    *,
    model: str,
    system: str,
    user_text: str,
    video_path: Path,
    public_url: str | None = None,
    client=None,
    images: list[str] | None = None,
) -> str:
    """Send Fable the mp4. Codex-equivalent: Files API + code-execution sandbox.
    Optional `images` are second-pass cut-reference JPEGs — never a stills-only reverse.
    """
    import anthropic

    if client is None:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=DESCRIBE_BUDGET_S)
    path = Path(video_path)
    extra = _fable_image_blocks(images)
    last_error: BaseException | None = None
    for label, content in fable_content_attempts(path, public_url=public_url, user_text=user_text):
        try:
            message = client.messages.create(
                model=model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=system,
                messages=[{'role': 'user', 'content': list(content) + extra}],
            )
            text = _message_text(message)
            if text:
                return text
            last_error = ReverseError(f'{model} returned an empty reverse prompt ({label})')
        except Exception as exc:
            last_error = exc
            if not _retryable_video_error(exc):
                raise ReverseError(f'{model} refused the video file: {exc}') from exc
            logger.warning('Fable %s path failed: %s', label, exc)

    file_id = None
    try:
        file_id = _anthropic_upload_video(client, path)
        message = client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system,
            messages=[{
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': user_text},
                    {'type': 'container_upload', 'file_id': file_id},
                    *extra,
                ],
            }],
            tools=[{'type': 'code_execution_20250825', 'name': 'code_execution'}],
        )
        text = _message_text(message)
        if text:
            return text
        raise ReverseError(f'{model} returned an empty reverse prompt (container_upload)')
    except ReverseError:
        raise
    except Exception as exc:
        last_error = exc
        raise ReverseError(f'{model} could not read the video file ({last_error})') from exc
    finally:
        if file_id:
            files_api = getattr(client, 'files', None) or getattr(getattr(client, 'beta', None), 'files', None)
            try:
                if files_api is not None:
                    files_api.delete(file_id)
            except Exception:
                logger.debug('could not delete Anthropic file %s', file_id)
