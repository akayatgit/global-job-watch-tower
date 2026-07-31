"""Extract job fields from a Scrapling Response of a LinkedIn jobs search page.

Handles both the logged-in layout (.job-card-container) and the
guest/public layout (.base-card).
"""

from dataclasses import dataclass
from datetime import date, datetime
import re

JOB_ID_RE = re.compile(r'(?:jobs/view/|currentJobId=)(\d+)')
URN_RE = re.compile(r'(\d+)$')


@dataclass
class ParsedJob:
    linkedin_job_id: str
    title: str
    company: str | None
    location: str | None
    job_url: str
    posted_date: date | None
    raw_text: str


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    return ' '.join(value.split()).strip() or None


def _job_id_from_card(card) -> str | None:
    for attr in ('data-job-id', 'data-occludable-job-id'):
        value = card.attrib.get(attr)
        if value and value.isdigit():
            return value
    urn = card.attrib.get('data-entity-urn', '')
    m = URN_RE.search(urn)
    if m:
        return m.group(1)
    for link in card.css('a'):
        href = link.attrib.get('href', '')
        m = JOB_ID_RE.search(href)
        if m:
            return m.group(1)
    return None


def _posted_date_from_card(card) -> date | None:
    for t in card.css('time'):
        dt = t.attrib.get('datetime')
        if dt:
            try:
                return datetime.strptime(dt[:10], '%Y-%m-%d').date()
            except ValueError:
                continue
    return None


def _first_text(card, selectors: list[str]) -> str | None:
    for sel in selectors:
        got = card.css(f'{sel}::text').getall()
        text = _clean(' '.join(got))
        if text:
            return text
    return None


def parse_jobs(page) -> list[ParsedJob]:
    """Parse all job cards on a Scrapling response page."""
    cards = page.css(
        '.job-card-container, li.jobs-search-results__list-item, '
        'li.scaffold-layout__list-item, .base-card'
    )
    jobs: list[ParsedJob] = []
    seen: set[str] = set()

    for card in cards:
        job_id = _job_id_from_card(card)
        if not job_id or job_id in seen:
            continue

        title = _first_text(card, [
            '.job-card-list__title strong',
            '.job-card-list__title',
            'a.job-card-container__link strong',
            'a.job-card-container__link',
            '.base-search-card__title',
            'h3',
        ])
        if not title:
            continue

        company = _first_text(card, [
            '.artdeco-entity-lockup__subtitle span',
            '.artdeco-entity-lockup__subtitle',
            '.job-card-container__primary-description',
            '.job-card-container__company-name',
            '.base-search-card__subtitle a',
            '.base-search-card__subtitle',
            'h4',
        ])

        location = _first_text(card, [
            '.job-card-container__metadata-wrapper li',
            '.job-card-container__metadata-item',
            '.artdeco-entity-lockup__caption li',
            '.artdeco-entity-lockup__caption',
            '.job-search-card__location',
        ])

        raw_text = _clean(' '.join(card.css('::text').getall())) or ''

        seen.add(job_id)
        jobs.append(ParsedJob(
            linkedin_job_id=job_id,
            title=title[:500],
            company=company[:300] if company else None,
            location=location[:300] if location else None,
            job_url=f'https://www.linkedin.com/jobs/view/{job_id}/',
            posted_date=_posted_date_from_card(card),
            raw_text=raw_text[:4000],
        ))

    return jobs


RESULTS_COUNT_RE = re.compile(r'([\d,]+)\+?\s+results?', re.IGNORECASE)


def parse_results_count(page) -> int | None:
    """Read LinkedIn's "N results" header so we don't paginate past the end."""
    header_text = ' '.join(page.css(
        '.jobs-search-results-list__subtitle ::text, '
        '.results-context-header__job-count::text, '
        'small::text, h1::text'
    ).getall())
    m = RESULTS_COUNT_RE.search(header_text)
    if not m:
        m = RESULTS_COUNT_RE.search(' '.join(page.css('::text').getall())[:5000])
    if m:
        try:
            return int(m.group(1).replace(',', ''))
        except ValueError:
            return None
    return None


def looks_like_login_page(page) -> bool:
    text = ' '.join(page.css('h1::text, h2::text, button::text').getall()).lower()
    return ('sign in' in text or 'join linkedin' in text) and 'job' not in text


def _page_blobs(page) -> tuple[str, str, str]:
    """Return (title, visible_text, html_excerpt) best-effort from a Scrapling page."""
    title = ''
    text = ''
    html = ''
    try:
        title = ' '.join(page.css('title::text').getall()).strip()
    except Exception:
        pass
    try:
        text = ' '.join(page.css('body ::text').getall())
        text = ' '.join(text.split())
    except Exception:
        try:
            text = ' '.join(page.css('::text').getall())
            text = ' '.join(text.split())
        except Exception:
            text = ''
    try:
        html = (getattr(page, 'html_content', None) or getattr(page, 'body', None) or '')
        if callable(html):
            html = html()
        html = str(html or '')[:8000]
    except Exception:
        html = ''
    return title, text, html


# Strong phrases — only count in *visible* text (never raw HTML: LinkedIn
# always embeds "recaptcha" / "captcha" in scripts even on healthy pages).
_HARD_VISIBLE_MARKERS = (
    'unusual activity',
    'security verification',
    "verify it's you",
    'verify it\'s you',
    'verify your identity',
    'we restricted your account',
    'temporarily restricted',
    'please complete a security check',
    'are you a robot',
    'complete the captcha',
    'solve this puzzle',
    'let\'s do a quick security check',
)

# Soft auth cues in visible text — only a block if we also got ZERO job cards
_SOFT_VISIBLE_MARKERS = (
    'sign in to continue',
    'sign in to see',
    'join to view',
    'session expired',
)


def detect_linkedin_block(page, *, http_status: int | None = None,
                          had_job_cards: bool = False) -> dict | None:
    """Real LinkedIn blocks only — never false-alarm on healthy job results.

    LinkedIn HTML always contains words like ``recaptcha`` / ``captcha`` in
    scripts. If we already have job cards — or the visible page clearly shows
    a results list — the page is usable: dismiss popups and keep scraping.
    """
    title, text, html = _page_blobs(page)
    visible = f'{title}\n{text}'.lower()

    if http_status in (401, 403, 429, 999):
        return {
            'reason': f'LinkedIn HTTP {http_status} — access denied / rate limited',
            'page_title': title,
            'page_text': text[:4000],
            'html_excerpt': html[:6000],
            'http_status': http_status,
        }

    # Healthy results page signals (even if our card CSS missed some)
    looks_like_results = (
        had_job_cards
        or 'jobs in' in visible
        or 'actively hiring' in visible
        or re.search(r'\d[\d,]*\+?\s+.+?\s+jobs', visible) is not None
        or 'base-serp-page' in html.lower()
        or 'jobs-guest-frontend' in html.lower()
        or 'd_jobs_guest_search' in html.lower()
        or 'jobs-search-results' in html.lower()
    )
    if looks_like_results:
        return None

    if looks_like_login_page(page):
        return {
            'reason': 'LinkedIn showed the login / join wall — session cookies may be stale',
            'page_title': title,
            'page_text': text[:4000],
            'html_excerpt': html[:6000],
            'http_status': http_status,
        }

    for marker in _HARD_VISIBLE_MARKERS:
        if marker in visible:
            return {
                'reason': f'LinkedIn security challenge (“{marker}”) — no job cards on page',
                'page_title': title,
                'page_text': text[:4000],
                'html_excerpt': html[:6000],
                'http_status': http_status,
            }

    for marker in _SOFT_VISIBLE_MARKERS:
        if marker in visible:
            return {
                'reason': f'LinkedIn auth wall (“{marker}”) — no job cards on page',
                'page_title': title,
                'page_text': text[:4000],
                'html_excerpt': html[:6000],
                'http_status': http_status,
            }

    html_l = html.lower()
    if '/checkpoint/challenge' in html_l and 'job' not in visible:
        return {
            'reason': 'No job cards and auth/challenge markup present',
            'page_title': title,
            'page_text': text[:4000],
            'html_excerpt': html[:6000],
            'http_status': http_status,
        }
    return None
