"""Where prompts are found — every source returns Candidates with provenance.

Sources are pluggable and independent: one failing (Instagram login gone,
Reddit rate-limit) never blocks the others. All network access goes through
an injectable fetcher so the extractors are unit-testable offline.

- reddit    public JSON listings, with Atom RSS fallback (JSON is 403-blocked
            from datacenter IPs as of 2026-09-10)
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
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from app.prompts.normalize import MAX_CJK_RATIO, MIN_PROMPT_CHARS, cjk_ratio, clean_text, read_prompt

logger = logging.getLogger(__name__)

USER_AGENT = (
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/128.0.0.0 Safari/537.36'
)
ATOM = '{http://www.w3.org/2005/Atom}'
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


@dataclass
class SourceReport:
    source: str
    fetched: int = 0
    kept: int = 0
    error: str | None = None

    def as_dict(self) -> dict[str, int | str | None]:
        return {
            'source': self.source,
            'fetched': self.fetched,
            'kept': self.kept,
            'error': self.error,
        }


def http_fetch(url: str, *, timeout: int = 30) -> str:
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': USER_AGENT,
            'Accept': 'application/json, application/atom+xml, application/rss+xml, text/html, */*',
        },
    )
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


CHROME_LINE_RE = re.compile(r'^\s*(?:[-*+•]|\d+[.)])\s')


def _is_chrome_paragraph(para: str) -> bool:
    cleaned = clean_text(para)
    if not cleaned:
        return True
    if cjk_ratio(cleaned) > MAX_CJK_RATIO:
        return True
    lines = [ln for ln in cleaned.split('\n') if ln.strip()]
    if not lines:
        return True
    # Bullet lists of short items (contents, tag lists) — no sentences
    listy = sum(1 for ln in lines if CHROME_LINE_RE.match(ln) or len(ln) < 48)
    if listy == len(lines) and not any(ln.rstrip().endswith(('.', '!', '?')) for ln in lines):
        return True
    return False


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
        # A paragraph that is a prompt by itself is taken alone — never glued
        # to the README chrome that happened to precede it.
        if len(para) >= MIN_PROMPT_CHARS and read_prompt(para).is_prompt:
            blocks.append(para)
            buffer = []
            continue
        # Table-of-contents lines, tag rows, and non-English index text are
        # chrome: they never start or join a merged block.
        if _is_chrome_paragraph(para):
            buffer = []
            continue
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


def _err_text(exc: BaseException) -> str:
    code = getattr(exc, 'code', None)
    reason = getattr(exc, 'reason', None)
    if code is not None:
        return f'HTTP {code} {reason or ""}'.strip()
    return str(exc)[:220]


def _strip_html(raw: str) -> str:
    text = html.unescape(raw or '')
    text = SCRIPT_RE.sub(' ', text)
    text = re.sub(r'<(br|/p|/div|/li|/h\d)[^>]*>', '\n', text, flags=re.I)
    text = html.unescape(TAG_RE.sub(' ', text))
    return re.sub(r'[ \t]+', ' ', text).strip()


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


# ---------------------------------------------------------------- reddit

def _posts_from_json(payload: object) -> list[dict]:
    children = ((payload.get('data') or {}).get('children') or []) if isinstance(payload, dict) else []
    posts: list[dict] = []
    for child in children:
        data = (child or {}).get('data') or {}
        permalink = str(data.get('permalink') or '')
        url = f'https://www.reddit.com{permalink}' if permalink.startswith('/') else (permalink or None)
        posted = data.get('created_utc')
        posted_at = (
            datetime.fromtimestamp(float(posted), tz=timezone.utc) if posted else None
        )
        posts.append({
            'title': str(data.get('title') or ''),
            'selftext': str(data.get('selftext') or ''),
            'html': '',
            'url': url,
            'author': str(data.get('author') or '') or None,
            'posted_at': posted_at,
        })
    return posts


def _atom_text(el: ET.Element | None) -> str:
    if el is None:
        return ''
    if el.text:
        return el.text
    return ''.join(el.itertext())


def _posts_from_feed(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    posts: list[dict] = []
    entries = root.findall(f'{ATOM}entry')
    if entries:
        for entry in entries:
            title = _atom_text(entry.find(f'{ATOM}title')).strip()
            link = entry.find(f'{ATOM}link')
            href = (link.get('href') if link is not None else '') or ''
            if not href:
                href = _atom_text(entry.find(f'{ATOM}id')).strip()
            author_el = entry.find(f'{ATOM}author/{ATOM}name')
            author = _atom_text(author_el).lstrip('/').removeprefix('u/').removeprefix('user/') or None
            content_el = entry.find(f'{ATOM}content')
            if content_el is None:
                content_el = entry.find(f'{ATOM}summary')
            html_body = html.unescape(_atom_text(content_el))
            posts.append({
                'title': title,
                'selftext': _strip_html(html_body),
                'html': html_body,
                'url': href or None,
                'author': author,
                'posted_at': _parse_iso_dt(_atom_text(entry.find(f'{ATOM}updated'))),
            })
        return posts

    channel = root.find('channel')
    items = (channel.findall('item') if channel is not None else []) or root.findall('item')
    for item in items:
        title = (item.findtext('title') or '').strip()
        href = (item.findtext('link') or '').strip()
        html_body = html.unescape(item.findtext('{http://purl.org/rss/1.0/modules/content/}encoded') or item.findtext('description') or '')
        author = (item.findtext('author') or '').lstrip('/').removeprefix('u/') or None
        posts.append({
            'title': title,
            'selftext': _strip_html(html_body),
            'html': html_body,
            'url': href or None,
            'author': author,
            'posted_at': None,
        })
    return posts


def _candidates_from_posts(posts: list[dict]) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set[str] = set()
    for post in posts:
        title = str(post.get('title') or '').strip()
        body = str(post.get('selftext') or '').strip()
        html_body = str(post.get('html') or '').strip()
        combined = body
        if title and title.lower() not in body.lower():
            combined = f'{title}\n\n{body}' if body else title
        blocks: list[str] = []
        if html_body:
            blocks.extend(html_to_blocks(html_body))
        if not blocks:
            blocks.extend(extract_prompt_blocks(combined))
        url = post.get('url')
        author = post.get('author')
        posted_at = post.get('posted_at')
        for block in blocks:
            reading = read_prompt(block)
            if not reading.is_prompt or reading.fingerprint in seen:
                continue
            seen.add(reading.fingerprint)
            out.append(Candidate(
                text=reading.text,
                source='reddit',
                source_url=url,
                author=author,
                title=(title or reading.title or '')[:300] or None,
                posted_at=posted_at,
            ))
    return out


def _json_has_bodies(posts: list[dict]) -> bool:
    return any((p.get('selftext') or '').strip() for p in posts)


def _status_code(exc: BaseException) -> int | None:
    code = getattr(exc, 'code', None)
    return int(code) if isinstance(code, int) else None


def reddit_candidates(
    subreddits: Iterable[str],
    *,
    limit: int = 40,
    fetch: Fetcher = http_fetch,
    reports: list[SourceReport] | None = None,
    pause_s: float | None = None,
    pause: Callable[[float], None] = time.sleep,
) -> list[Candidate]:
    """JSON first; Atom RSS when JSON 403s or returns link-only posts.

    Reddit rate-limits bursts (seven subs in two seconds earned HTTP 429 on
    2026-09-10), so subs are spaced `pause_s` apart, a 403 on JSON switches
    the rest of the run to RSS only, and a 429 stops touching Reddit for
    this run — the remaining subs are reported as skipped, not failed."""
    from app import config

    out: list[Candidate] = []
    cap = min(max(int(limit), 1), 100)
    if pause_s is None:
        pause_s = float(getattr(config, 'PROMPT_REDDIT_PAUSE_S', 8.0))
    json_blocked = False
    rate_limited = False
    first = True
    for sub in subreddits:
        sub = sub.strip().lstrip('r/').strip('/')
        if not sub:
            continue
        report = SourceReport(source=f'reddit r/{sub}')
        if rate_limited:
            report.error = 'skipped — Reddit rate-limited (HTTP 429) earlier this run'
            if reports is not None:
                reports.append(report)
            continue
        if not first and pause_s > 0:
            pause(pause_s)
        first = False
        json_url = f'https://www.reddit.com/r/{sub}/new.json?limit={cap}&raw_json=1'
        rss_url = f'https://www.reddit.com/r/{sub}/new.rss'
        posts: list[dict] = []
        errors: list[str] = []
        if not json_blocked:
            try:
                payload = json.loads(fetch(json_url))
                posts = _posts_from_json(payload)
            except Exception as exc:
                errors.append(_err_text(exc))
                logger.warning('reddit JSON failed r/%s: %s', sub, exc)
                code = _status_code(exc)
                if code == 403:
                    json_blocked = True
                elif code == 429:
                    rate_limited = True

        if not rate_limited and not _json_has_bodies(posts):
            if errors and pause_s > 0:
                pause(min(pause_s, 3.0))
            try:
                rss_posts = _posts_from_feed(fetch(rss_url))
                if rss_posts:
                    posts = rss_posts
                    errors = []
            except Exception as exc:
                errors.append(_err_text(exc))
                logger.warning('reddit RSS failed r/%s: %s', sub, exc)
                if _status_code(exc) == 429:
                    rate_limited = True

        report.fetched = len(posts)
        kept = _candidates_from_posts(posts)
        report.kept = len(kept)
        if errors and not kept:
            report.error = ' · '.join(errors)
        out.extend(kept)
        if reports is not None:
            reports.append(report)
    return out


# ------------------------------------------------------------------- web

def web_candidates(
    urls: Iterable[str],
    *,
    fetch: Fetcher = http_fetch,
    reports: list[SourceReport] | None = None,
) -> list[Candidate]:
    out: list[Candidate] = []
    for url in urls:
        url = url.strip()
        if not url:
            continue
        host = urllib.parse.urlparse(url).netloc.lower()
        source = 'promptbase' if 'promptbase' in host else 'web'
        report = SourceReport(source=f'web {host or url[:40]}')
        try:
            page = fetch(url)
        except Exception as exc:
            report.error = _err_text(exc)
            logger.warning('web source failed %s: %s', url, exc)
            if reports is not None:
                reports.append(report)
            continue
        kept: list[Candidate] = []
        raw_blocks = html_to_blocks(page)
        # Markdown / raw GitHub pages have no HTML tags — still mine fences + paragraphs
        if not raw_blocks:
            raw_blocks = extract_prompt_blocks(page)
        report.fetched = len(raw_blocks)
        for block in raw_blocks:
            reading = read_prompt(block)
            if reading.is_prompt:
                kept.append(Candidate(
                    text=reading.text, source=source, source_url=url, author=host or None,
                    title=reading.title,
                ))
        report.kept = len(kept)
        out.extend(kept)
        if reports is not None:
            reports.append(report)
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


def instagram_candidates(
    tags: Iterable[str],
    *,
    fetch: Fetcher = browser_fetch,
    reports: list[SourceReport] | None = None,
) -> list[Candidate]:
    out: list[Candidate] = []
    for tag in tags:
        tag = tag.strip().lstrip('#')
        if not tag:
            continue
        url = f'https://www.instagram.com/explore/tags/{urllib.parse.quote(tag)}/'
        report = SourceReport(source=f'instagram #{tag}')
        try:
            page = fetch(url)
        except Exception as exc:
            report.error = _err_text(exc)
            logger.warning('instagram source failed #%s: %s', tag, exc)
            if reports is not None:
                reports.append(report)
            continue
        captions = instagram_captions(page)
        report.fetched = len(captions)
        kept: list[Candidate] = []
        for caption, code in captions:
            for block in extract_prompt_blocks(caption):
                kept.append(Candidate(
                    text=block,
                    source='instagram',
                    source_url=f'https://www.instagram.com/p/{code}/' if code else url,
                    title=f'#{tag}',
                ))
        report.kept = len(kept)
        out.extend(kept)
        if reports is not None:
            reports.append(report)
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

def gather_with_reports(
    *,
    fetch: Fetcher = http_fetch,
    browser: Fetcher | None = None,
    pause: Callable[[float], None] = time.sleep,
) -> tuple[list[Candidate], list[dict]]:
    """Every configured source, plus a per-source fetched/kept/error report.
    Never raises."""
    from app import config

    limit = int(getattr(config, 'PROMPT_SOURCE_LIMIT', 40))
    out: list[Candidate] = []
    reports: list[SourceReport] = []
    subs = [s for s in (getattr(config, 'PROMPT_REDDIT_SUBS', '') or '').split(',') if s.strip()]
    if subs:
        out.extend(reddit_candidates(subs, limit=limit, fetch=fetch, reports=reports, pause=pause))
    urls = [u for u in (getattr(config, 'PROMPT_WEB_URLS', '') or '').split(',') if u.strip()]
    if urls:
        out.extend(web_candidates(urls, fetch=fetch, reports=reports))
    tags = [t for t in (getattr(config, 'PROMPT_INSTAGRAM_TAGS', '') or '').split(',') if t.strip()]
    if tags:
        out.extend(instagram_candidates(tags, fetch=browser or browser_fetch, reports=reports))
    if not subs and not urls and not tags:
        reports.append(SourceReport(
            source='config',
            error='no sources configured (PROMPT_REDDIT_SUBS / PROMPT_WEB_URLS empty)',
        ))
    return out, [r.as_dict() for r in reports]


def gather_candidates(
    *,
    fetch: Fetcher = http_fetch,
    browser: Fetcher | None = None,
    pause: Callable[[float], None] = time.sleep,
) -> list[Candidate]:
    """Every configured source, in one list. Never raises."""
    candidates, _reports = gather_with_reports(fetch=fetch, browser=browser, pause=pause)
    return candidates
