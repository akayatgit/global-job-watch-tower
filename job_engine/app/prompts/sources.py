"""Where prompts are found — every source returns Candidates with provenance.

Sources are pluggable and independent: one failing (Instagram login gone,
Reddit rate-limit) never blocks the others. All network access goes through
an injectable fetcher so the extractors are unit-testable offline.

- reddit    public JSON listings of prompt subreddits (no auth)
- web       any public page listed in PROMPT_WEB_URLS (blogs, galleries)
- instagram hashtag pages through the tower's logged-in stealth browser
            (best effort — Instagram is hostile to scraping; off by default)
- manual    Ashok pastes / forwards a prompt on Telegram (/addprompt)
"""

from __future__ import annotations

import html
import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from app.prompts.normalize import MIN_PROMPT_CHARS, read_prompt

logger = logging.getLogger(__name__)

USER_AGENT = (
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/128.0 Safari/537.36 PromptTower/1.0'
)
FENCE_RE = re.compile(r'```(?:[a-z]*\n)?(.*?)```', re.S)
TAG_RE = re.compile(r'<[^>]+>')
SCRIPT_RE = re.compile(r'<(script|style)[^>]*>.*?</\1>', re.S | re.I)
BLOCK_TAG_RE = re.compile(r'<(pre|code|blockquote)[^>]*>(.*?)</\1>', re.S | re.I)
PARA_SPLIT_RE = re.compile(r'\n\s*\n')
IG_CAPTION_RE = re.compile(r'"caption"\s*:\s*\{[^{}]*?"text"\s*:\s*"((?:[^"\\]|\\.)*)"', re.S)
IG_SHORTCODE_RE = re.compile(r'"shortcode"\s*:\s*"([A-Za-z0-9_-]{5,20})"')

Fetcher = Callable[[str], str]


@dataclass
class Candidate:
    text: str
    source: str
    source_url: str | None = None
    author: str | None = None
    title: str | None = None
    posted_at: datetime | None = None


def http_fetch(url: str, *, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': '*/*'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', errors='replace')


def browser_fetch(url: str) -> str:
    """Logged-in stealth Chrome (same profile the LinkedIn lane uses).
    Imported lazily — scrapling is heavy and absent in unit tests."""
    from scrapling.fetchers import StealthySession

    from app import config
    from app.runtime_settings import get_headless

    with StealthySession(
        headless=get_headless(),
        real_chrome=True,
        user_data_dir=str(config.CHROME_BOT_PROFILE),
    ) as session:
        page = session.fetch(url)
        raw = getattr(page, 'html_content', None) or getattr(page, 'body', None) or ''
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8', errors='replace')
        return str(raw)


def extract_prompt_blocks(text: str) -> list[str]:
    """Prompt-looking blocks inside free text: fenced code first, then
    paragraphs merged until they read as a prompt."""
    raw = html.unescape(text or '')
    blocks: list[str] = []
    for fenced in FENCE_RE.findall(raw):
        if len(fenced.strip()) >= MIN_PROMPT_CHARS:
            blocks.append(fenced.strip())
    remainder = FENCE_RE.sub('\n', raw)
    paragraphs = [p.strip() for p in PARA_SPLIT_RE.split(remainder) if p.strip()]
    buffer: list[str] = []
    for para in paragraphs:
        buffer.append(para)
        joined = '\n'.join(buffer)
        if len(joined) >= MIN_PROMPT_CHARS and read_prompt(joined).is_prompt:
            blocks.append(joined)
            buffer = []
    if buffer:
        joined = '\n'.join(buffer)
        if read_prompt(joined).is_prompt:
            blocks.append(joined)
    # Keep the ones that actually read as prompts, longest-first, unique
    seen: set[str] = set()
    out: list[str] = []
    for block in sorted(blocks, key=len, reverse=True):
        reading = read_prompt(block)
        if not reading.is_prompt or reading.fingerprint in seen:
            continue
        seen.add(reading.fingerprint)
        out.append(reading.text)
    return out


# ---------------------------------------------------------------- reddit

def reddit_candidates(
    subreddits: Iterable[str], *, limit: int = 40, fetch: Fetcher = http_fetch,
) -> list[Candidate]:
    out: list[Candidate] = []
    for sub in subreddits:
        sub = sub.strip().lstrip('r/').strip('/')
        if not sub:
            continue
        url = f'https://www.reddit.com/r/{sub}/new.json?limit={min(max(limit, 1), 100)}&raw_json=1'
        try:
            payload = json.loads(fetch(url))
        except Exception as exc:
            logger.warning('reddit source failed r/%s: %s', sub, exc)
            continue
        children = ((payload.get('data') or {}).get('children') or []) if isinstance(payload, dict) else []
        for child in children:
            data = child.get('data') or {}
            body = str(data.get('selftext') or '')
            if not body:
                continue
            permalink = data.get('permalink') or ''
            posted = data.get('created_utc')
            posted_at = (
                datetime.fromtimestamp(float(posted), tz=timezone.utc) if posted else None
            )
            for block in extract_prompt_blocks(body):
                out.append(Candidate(
                    text=block,
                    source='reddit',
                    source_url=f'https://www.reddit.com{permalink}' if permalink else None,
                    author=str(data.get('author') or '') or None,
                    title=str(data.get('title') or '')[:300] or None,
                    posted_at=posted_at,
                ))
    return out


# ------------------------------------------------------------------- web

def html_to_blocks(page_html: str) -> list[str]:
    """Prefer <pre>/<code>/<blockquote>; then the stripped body text."""
    cleaned = SCRIPT_RE.sub(' ', page_html or '')
    blocks: list[str] = []
    for _tag, inner in BLOCK_TAG_RE.findall(cleaned):
        text = html.unescape(TAG_RE.sub(' ', inner))
        text = re.sub(r'[ \t]+', ' ', text).strip()
        if len(text) >= MIN_PROMPT_CHARS:
            blocks.append(text)
    body = re.sub(r'<(br|/p|/div|/li|/h\d)[^>]*>', '\n', cleaned, flags=re.I)
    body = html.unescape(TAG_RE.sub(' ', body))
    body = re.sub(r'[ \t]+', ' ', body)
    blocks.extend(extract_prompt_blocks(body))
    seen: set[str] = set()
    unique: list[str] = []
    for block in blocks:
        key = read_prompt(block).fingerprint
        if key in seen:
            continue
        seen.add(key)
        unique.append(block)
    return unique


def web_candidates(urls: Iterable[str], *, fetch: Fetcher = http_fetch) -> list[Candidate]:
    out: list[Candidate] = []
    for url in urls:
        url = url.strip()
        if not url:
            continue
        try:
            page = fetch(url)
        except Exception as exc:
            logger.warning('web source failed %s: %s', url, exc)
            continue
        host = urllib.parse.urlparse(url).netloc.lower()
        source = 'promptbase' if 'promptbase' in host else 'web'
        for block in html_to_blocks(page):
            reading = read_prompt(block)
            if reading.is_prompt:
                out.append(Candidate(text=reading.text, source=source, source_url=url, author=host))
    return out


# ------------------------------------------------------------- instagram

def instagram_captions(page_html: str) -> list[tuple[str, str | None]]:
    """(caption, shortcode-or-None) pairs from Instagram's embedded JSON."""
    captions = [
        json.loads(f'"{raw}"') if '\\' in raw else raw
        for raw in IG_CAPTION_RE.findall(page_html or '')
    ]
    codes = IG_SHORTCODE_RE.findall(page_html or '')
    out: list[tuple[str, str | None]] = []
    for index, caption in enumerate(captions):
        code = codes[index] if index < len(codes) else None
        out.append((caption, code))
    return out


def instagram_candidates(tags: Iterable[str], *, fetch: Fetcher = browser_fetch) -> list[Candidate]:
    out: list[Candidate] = []
    for tag in tags:
        tag = tag.strip().lstrip('#')
        if not tag:
            continue
        url = f'https://www.instagram.com/explore/tags/{urllib.parse.quote(tag)}/'
        try:
            page = fetch(url)
        except Exception as exc:
            logger.warning('instagram source failed #%s: %s', tag, exc)
            continue
        for caption, code in instagram_captions(page):
            for block in extract_prompt_blocks(caption):
                out.append(Candidate(
                    text=block,
                    source='instagram',
                    source_url=f'https://www.instagram.com/p/{code}/' if code else url,
                    title=f'#{tag}',
                ))
    return out


# ---------------------------------------------------------------- manual

def manual_candidate(text: str, *, author: str | None = None, source_url: str | None = None) -> Candidate | None:
    blocks = extract_prompt_blocks(text or '')
    if not blocks:
        reading = read_prompt(text or '')
        if not reading.is_prompt:
            return None
        blocks = [reading.text]
    return Candidate(text=blocks[0], source='manual', author=author, source_url=source_url)


# --------------------------------------------------------------- gather

def gather_candidates(*, fetch: Fetcher = http_fetch, browser: Fetcher | None = None) -> list[Candidate]:
    """Every configured source, in one list. Never raises."""
    from app import config

    limit = int(getattr(config, 'PROMPT_SOURCE_LIMIT', 40))
    out: list[Candidate] = []
    subs = [s for s in (getattr(config, 'PROMPT_REDDIT_SUBS', '') or '').split(',') if s.strip()]
    if subs:
        out.extend(reddit_candidates(subs, limit=limit, fetch=fetch))
    urls = [u for u in (getattr(config, 'PROMPT_WEB_URLS', '') or '').split(',') if u.strip()]
    if urls:
        out.extend(web_candidates(urls, fetch=fetch))
    tags = [t for t in (getattr(config, 'PROMPT_INSTAGRAM_TAGS', '') or '').split(',') if t.strip()]
    if tags:
        out.extend(instagram_candidates(tags, fetch=browser or browser_fetch))
    return out
