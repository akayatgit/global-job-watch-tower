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
