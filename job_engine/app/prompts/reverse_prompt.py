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
    timestamped prompt ─▶ post_reel.compose_reel ─▶ reel MP4

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
MIN_VIDEO_BYTES = 50_000
DESCRIBE_BUDGET_S = 600
DEFAULT_KEYWORD = 'PRODUCT'
# Gemini 2.5 Flash thinking is ON by default and shares max_output_tokens.
# Reverse #7 (2026-09-11) died mid-JSON at 4096 — thinking ate the budget,
# parse_reading stored the truncated blob as keyword PRODUCT. 32k + thinking
# off leaves room for a full cinematic prompt (typically 3–8k characters).
MAX_OUTPUT_TOKENS = 32768
THINKING_BUDGET = 0
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
- The JSON object MUST be complete: close every string and the object. Never stop mid-sentence or mid-beat. A short cinematic clip typically needs 3000–8000 characters — write them all.
- Also list every hard cut / shot change as `cuts`. These are the frames a filmmaker needs to recreate the clip — not evenly spaced stills.

Quality bar — this exemplar shows the depth, structure and vocabulary expected. Match its density; do not copy its content:
---
{exemplar}
---

Return STRICT JSON with exactly three keys and nothing else:
{{"keyword": "<ONE uppercase word people would comment to get this prompt — the product category, e.g. SKINCARE, COFFEE, WATCH>", "prompt": "<the full timestamped prompt as one string with newlines>", "cuts": [{{"start": 0.0, "end": 1.8}}]}}
`cuts` covers the full duration in order. `start` / `end` are seconds at the first and last frame of that shot. Do not put the cuts array inside the prompt string."""

USER_PROMPT = (
    'Reverse-engineer this {duration} product video into the generation prompt described in your '
    'instructions. Cover the full duration with timestamped segments. List every hard cut in `cuts`. '
    'Return only complete JSON — close the prompt string, the cuts array and the object. Never stop mid-sentence.'
)

USER_PROMPT_RETRY = (
    'Your previous JSON was cut off mid-prompt. Return ONLY the complete JSON object '
    '{{"keyword":"<ONE uppercase word>","prompt":"<full timestamped prompt>",'
    '"cuts":[{{"start":0.0,"end":1.8}}]}} covering this {duration} clip. Close every string, '
    'the cuts array and the object. Do not stop mid-sentence.'
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


def plan_reference_times(
    cuts: list[tuple[float, float]],
    *,
    duration_s: float | None,
    count: int = REFERENCE_FRAME_COUNT,
) -> list[float]:
    """~14 timestamps from hard cuts — start + end of each shot.

    Not an equal grid. Extra slots go to interiors of the longest cuts.
    Surplus short cuts are dropped; the first start and last end stay.
    """
    count = max(2, int(count or REFERENCE_FRAME_COUNT))
    ranges = normalize_cuts(cuts, duration_s)
    if not ranges:
        end = duration_s if duration_s and duration_s > 0 else 0.0
        ranges = [(0.0, end)]

    def _end_in_shot(start: float, end: float) -> float:
        if end - start > CUT_END_INSET_S * 2:
            return end - CUT_END_INSET_S
        return end if end > start else start

    points: list[float] = []
    if all(abs(end - start) < 0.02 for start, end in ranges):
        points = [start for start, _end in ranges]
    else:
        for start, end in ranges:
            points.append(start)
            points.append(_end_in_shot(start, end))
        points[0] = ranges[0][0]
        points[-1] = _end_in_shot(*ranges[-1])

    # Always keep the first frame of the first cut and the last of the last.
    must = {round(ranges[0][0], 3), round(_end_in_shot(*ranges[-1]), 3)}

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

    points = _dedupe(points)
    if len(points) > count:
        ranked = sorted(ranges, key=lambda pair: pair[1] - pair[0], reverse=True)
        keep: list[float] = [ranges[0][0], _end_in_shot(*ranges[-1])]
        for start, end in ranked:
            if len(_dedupe(keep)) >= count:
                break
            keep.append(start)
            keep.append(_end_in_shot(start, end))
        points = _dedupe(sorted(keep))[:count]
        for required in must:
            if required not in points and len(points) == count:
                points[-2] = required
                points = _dedupe(sorted(points))[:count]
    elif len(points) < count:
        longest = sorted(ranges, key=lambda pair: pair[1] - pair[0], reverse=True)
        extras: list[float] = []
        for frac in (0.35, 0.7, 0.2, 0.85, 0.5):
            for start, end in longest:
                span = end - start
                if span < 0.3:
                    continue
                extras.append(start + span * frac)
            merged = _dedupe(sorted(points + extras))
            if len(merged) >= count:
                points = merged[:count]
                break
        else:
            points = _dedupe(sorted(points + extras))[:count]
    return points


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
        try:
            data = grab(video_path, t)
        except Exception as exc:
            logger.warning('reference frame %s at %.3fs failed: %s', index, t, exc)
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

    Small clips become an explicit ``data:video/mp4;base64,…`` URI.
    Larger ones use our public ``.mp4`` asset URL (same suffix Google
    needs to guess).
    """
    url = (public_url or '').strip()
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if (
        size > DATA_URI_MAX_BYTES
        and url.lower().startswith(('http://', 'https://'))
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
    `complete` are injectable for tests. Never extract stills ourselves.
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
) -> ReverseReading:
    """Gemini (Replicate) watches the clip. Thinking is off so the token
    budget is the JSON. If the first JSON still does not close, one retry.
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
    inputs = {
        'prompt': prompt_tmpl.format(duration=_duration_label(duration_s)),
        'videos': [video_input_for_vision(video_path, public_url=public_url)],
        'system_instruction': build_instruction(duration_s=duration_s, exemplar=exemplar),
        'temperature': 0.7,
        'max_output_tokens': MAX_OUTPUT_TOKENS,
        'thinking_budget': THINKING_BUDGET,
    }
    output = run(model, input=inputs)
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
        )
        if json_reading_complete(retry.raw) or len(retry.prompt) > len(reading.prompt):
            return retry
    return reading


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
            return retry
    return reading


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


def _openai_complete(
    *,
    model: str,
    system: str,
    user_text: str,
    video_path: Path,
    public_url: str | None = None,
    client=None,
) -> str:
    """Send Astra the mp4. Codex-equivalent: file in a code-interpreter sandbox."""
    from openai import OpenAI

    if client is None:
        client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=DESCRIBE_BUDGET_S)
    path = Path(video_path)
    last_error: BaseException | None = None
    for label, content in astra_content_attempts(path, public_url=public_url, user_text=user_text):
        try:
            response = client.responses.create(
                model=model,
                instructions=system,
                input=[{'role': 'user', 'content': content}],
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
) -> str:
    """Send Fable the mp4. Codex-equivalent: Files API + code-execution sandbox."""
    import anthropic

    if client is None:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=DESCRIBE_BUDGET_S)
    path = Path(video_path)
    last_error: BaseException | None = None
    for label, content in fable_content_attempts(path, public_url=public_url, user_text=user_text):
        try:
            message = client.messages.create(
                model=model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=system,
                messages=[{'role': 'user', 'content': content}],
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
