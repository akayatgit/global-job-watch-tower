"""Reverse prompt — a best-performing product video → the prompt behind it.

Ashok (2026-09-10): "/igtovid or /pintovid … ask for the Instagram or
Pinterest url, download the video, take 6 frames, pass the video to Gemini
to get a timestamp-based prompt … place the video, the prompt and the
screenshots as storyboard frames in the same final template and render the
final video. This is a very important feature — this is the best
performing post for which we get the reverse prompt and post it."

Pipeline (worker, `app.tasks.reverse_prompt_video`):

    URL ─▶ fetch_video ─▶ stored clip ─▶ describe_video (Gemini on
    Replicate, exemplar as the quality bar) ─▶ keyword + timestamped
    prompt ─▶ post_reel.compose_reel (clip · 6-frame storyboard ·
    scrolling prompt) ─▶ reel MP4

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

import html as html_lib
import json
import logging
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
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
MIN_VIDEO_BYTES = 50_000
DESCRIBE_BUDGET_S = 600
DEFAULT_KEYWORD = 'PRODUCT'

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
    """Pinterest often exposes only an HLS playlist — ffmpeg stitches it."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'clip.mp4'
        headers = f'User-Agent: {USER_AGENT}\r\n' + (f'Referer: {referer}\r\n' if referer else '')
        cmd = [
            ffmpeg, '-y', '-v', 'error', '-headers', headers, '-i', playlist_url,
            '-c', 'copy', '-bsf:a', 'aac_adtstoasc', '-movflags', '+faststart', str(out),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT_S)
        if result.returncode != 0 or not out.is_file():
            raise ReverseError(f'HLS download failed: {(result.stderr or "").strip()[:200]}')
        if out.stat().st_size > max_bytes:
            raise ReverseError(f'video is larger than {max_bytes // (1024 * 1024)} MB — send a shorter clip')
        return out.read_bytes()


def looks_like_video(data: bytes) -> bool:
    head = data[:64]
    return b'ftyp' in head or head.startswith(b'\x1aE\xdf\xa3') or head.startswith(b'RIFF')


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
            candidates = extract_media_urls(browser_fetch(page_url))
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
- End with a one-line "Style:" summary.

Quality bar — this exemplar shows the depth, structure and vocabulary expected. Match its density; do not copy its content:
---
{exemplar}
---

Return STRICT JSON with exactly two keys and nothing else:
{{"keyword": "<ONE uppercase word people would comment to get this prompt — the product category, e.g. SKINCARE, COFFEE, WATCH>", "prompt": "<the full timestamped prompt as one string with newlines>"}}"""

USER_PROMPT = (
    'Reverse-engineer this {duration} product video into the generation prompt described in your '
    'instructions. Cover the full duration with timestamped segments. Return only the JSON.'
)


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


def parse_reading(text: str, *, model: str = '') -> ReverseReading:
    """The model is asked for JSON; tolerate fences, prose around it, or a
    bare prompt (then the keyword falls back to PRODUCT)."""
    raw = (text or '').strip()
    body = _strip_fences(raw)
    data = None
    try:
        data = json.loads(body)
    except ValueError:
        match = re.search(r'\{.*\}', body, re.S)
        if match:
            try:
                data = json.loads(match.group(0))
            except ValueError:
                data = None
    if isinstance(data, dict) and str(data.get('prompt') or '').strip():
        return ReverseReading(keyword=clean_keyword(data.get('keyword')), prompt=str(data['prompt']).strip(), model=model, raw=raw)
    if len(body) < 80:
        raise ReverseError(f'vision model returned no prompt: {body[:120] or "(empty)"}')
    return ReverseReading(keyword=DEFAULT_KEYWORD, prompt=body, model=model, raw=raw)


def _output_text(output) -> str:
    if output is None:
        return ''
    if isinstance(output, (list, tuple)):
        return ''.join(str(part) for part in output)
    if hasattr(output, 'read'):
        return output.read().decode('utf-8', errors='replace')
    return str(output)


def describe_video(
    video_path: Path,
    *,
    duration_s: float | None,
    run: Callable[..., object] | None = None,
    log: Callable[[str], None] | None = None,
    exemplar: str | None = None,
) -> ReverseReading:
    """Gemini (Replicate) watches the clip and returns keyword + timestamped
    prompt. `run(model, input) -> output` is injectable for tests."""
    model = config.REPLICATE_VISION_MODEL
    if run is None:
        token = getattr(config, 'REPLICATE_API_TOKEN', '')
        if not token:
            raise ReverseError('REPLICATE_API_TOKEN missing in job_engine/.env')
        import replicate

        from app.prompts.video_creator import replicate_render

        client = replicate.Client(api_token=token)

        def run(model, input):  # noqa: A001
            return replicate_render(client, model, input=input, budget_s=DESCRIBE_BUDGET_S, log=log)

    handle = open(video_path, 'rb')  # noqa: SIM115 — closed after the call
    inputs = {
        'prompt': USER_PROMPT.format(duration=_duration_label(duration_s)),
        'videos': [handle],
        'system_instruction': build_instruction(duration_s=duration_s, exemplar=exemplar),
        'temperature': 0.7,
        'max_output_tokens': 4096,
    }
    try:
        output = run(model, input=inputs)
    finally:
        handle.close()
    return parse_reading(_output_text(output), model=model)
