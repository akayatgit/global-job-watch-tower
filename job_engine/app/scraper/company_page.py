"""Parse LinkedIn company profile / about pages."""

from __future__ import annotations

from dataclasses import dataclass
import re

from app.scraper.parse import COMPANY_URL_RE

FOLLOWERS_RE = re.compile(
    r'([\d,.]+)\s*([KkMm])?\s+followers?\b',
    re.I,
)
EMPLOYEES_RE = re.compile(
    r'(?:^|[^\d])([\d,]+)\s*[-–—]\s*([\d,]+)\s+employees?\b'
    r'|([\d,]+)\+?\s+employees?\b'
    r'|company\s+size\s*[:\-]?\s*([\d,]+)\s*[-–—]\s*([\d,]+)',
    re.I,
)


@dataclass
class CompanyProfile:
    linkedin_url: str | None = None
    logo_url: str | None = None
    tagline: str | None = None
    about_text: str | None = None
    follower_count: int | None = None
    employee_count_min: int | None = None
    employee_count_max: int | None = None
    employee_count_label: str | None = None


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    return ' '.join(value.split()).strip() or None


def _parse_int_compact(num: str, suffix: str | None = None) -> int | None:
    try:
        n = float(num.replace(',', ''))
    except ValueError:
        return None
    if suffix:
        s = suffix.upper()
        if s == 'K':
            n *= 1_000
        elif s == 'M':
            n *= 1_000_000
    return int(n)


def parse_follower_count(text: str) -> int | None:
    m = FOLLOWERS_RE.search(text or '')
    if not m:
        return None
    return _parse_int_compact(m.group(1), m.group(2))


def parse_employee_size(text: str) -> tuple[int | None, int | None, str | None]:
    m = EMPLOYEES_RE.search(text or '')
    if not m:
        return None, None, None
    if m.group(1) and m.group(2):
        lo = _parse_int_compact(m.group(1))
        hi = _parse_int_compact(m.group(2))
        label = f'{m.group(1)}-{m.group(2)} employees'
        return lo, hi, label
    if m.group(4) and m.group(5):
        lo = _parse_int_compact(m.group(4))
        hi = _parse_int_compact(m.group(5))
        label = f'{m.group(4)}-{m.group(5)} employees'
        return lo, hi, label
    if m.group(3):
        n = _parse_int_compact(m.group(3))
        label = f'{m.group(3)} employees'
        return n, n, label
    return None, None, None


def _logo_from_page(page) -> str | None:
    for sel in (
        'img.org-top-card-primary-content__logo',
        'img.EntityPhoto-circle-xlarge',
        'img.EntityPhoto-square-xlarge',
        'img.org-top-card-primary-content__logo-image',
        '.org-top-card-primary-content__logo-container img',
        'img[alt*="logo" i]',
    ):
        try:
            for img in page.css(sel):
                src = img.attrib.get('src') or img.attrib.get('data-delayed-url') or ''
                if src and 'media.licdn.com' in src and 'data:image' not in src:
                    return src.split('?')[0][:800]
        except Exception:
            continue
    # Fallback: largest-looking licdn image near top
    try:
        for img in page.css('img'):
            src = img.attrib.get('src') or ''
            if 'media.licdn.com' in src and 'company-logo' in src:
                return src.split('?')[0][:800]
    except Exception:
        pass
    return None


def _canonical_company_url(page, fallback: str | None = None) -> str | None:
    try:
        for link in page.css('link[rel="canonical"]'):
            href = link.attrib.get('href') or ''
            m = COMPANY_URL_RE.search(href)
            if m:
                return f'https://www.linkedin.com/company/{m.group(2).rstrip("/")}/'
    except Exception:
        pass
    if fallback:
        m = COMPANY_URL_RE.search(fallback)
        if m:
            return f'https://www.linkedin.com/company/{m.group(2).rstrip("/")}/'
    return fallback


def parse_company_page(page, *, page_url: str | None = None) -> CompanyProfile:
    """Extract logo, tagline, about, followers, employee size from a company page."""
    blob = ''
    try:
        blob = _clean(' '.join(page.css('::text').getall())) or ''
    except Exception:
        blob = ''

    tagline = None
    for sel in (
        'p.org-top-card-summary__tagline',
        '.org-top-card-summary__tagline',
        '.org-top-card-summary-info-list__info-item',
    ):
        try:
            t = _clean(' '.join(page.css(f'{sel}::text').getall()))
        except Exception:
            t = None
        if t and 8 <= len(t) <= 400 and 'follower' not in t.lower():
            tagline = t
            break

    about = None
    for sel in (
        '.org-about-module__margin-bottom .break-words',
        '.org-about-company-module__company-details',
        'section.about-us .break-words',
        '#about-us .break-words',
        '.org-page-details-module__card-spacing p',
    ):
        try:
            t = _clean(' '.join(page.css(f'{sel} ::text').getall()))
        except Exception:
            t = None
        if t and len(t) > 40:
            about = t[:4000]
            break
    if not about and blob:
        # Soft fallback — first ~600 chars after "About"
        m = re.search(r'About\s+(.{80,900})', blob, re.I | re.S)
        if m:
            about = _clean(m.group(1))[:1200]

    followers = parse_follower_count(blob)
    emin, emax, elabel = parse_employee_size(blob)

    return CompanyProfile(
        linkedin_url=_canonical_company_url(page, page_url),
        logo_url=_logo_from_page(page),
        tagline=tagline,
        about_text=about,
        follower_count=followers,
        employee_count_min=emin,
        employee_count_max=emax,
        employee_count_label=elabel,
    )


def company_bits_from_job_page(page) -> CompanyProfile:
    """Pull whatever company identity is visible on a job detail page."""
    blob = ''
    try:
        blob = _clean(' '.join(page.css('::text').getall())) or ''
    except Exception:
        blob = ''

    linkedin_url = None
    try:
        for link in page.css(
            'a[href*="/company/"], '
            '.job-details-jobs-unified-top-card__company-name a, '
            '.jobs-company__box a'
        ):
            href = (link.attrib.get('href') or '').split('?')[0]
            m = COMPANY_URL_RE.search(href)
            if m:
                slug = m.group(2).rstrip('/')
                if slug.lower() not in ('jobs', 'search'):
                    linkedin_url = f'https://www.linkedin.com/company/{slug}/'
                    break
    except Exception:
        pass

    logo = None
    for sel in (
        'img.EntityPhoto-square-1',
        'img.EntityPhoto-circle-3',
        '.jobs-company__company-logo img',
        '.job-details-jobs-unified-top-card__company-logo img',
        'img[alt*="logo" i]',
    ):
        try:
            for img in page.css(sel):
                src = img.attrib.get('src') or img.attrib.get('data-delayed-url') or ''
                if src and 'media.licdn.com' in src:
                    logo = src.split('?')[0][:800]
                    break
        except Exception:
            continue
        if logo:
            break

    tagline = None
    for sel in (
        '.jobs-company__company-name + p',
        '.jobs-company__box p',
        '.artdeco-entity-lockup__subtitle',
    ):
        try:
            t = _clean(' '.join(page.css(f'{sel}::text').getall()))
        except Exception:
            t = None
        if t and 12 <= len(t) <= 400 and 'follower' not in t.lower():
            tagline = t
            break

    followers = parse_follower_count(blob)
    emin, emax, elabel = parse_employee_size(blob)

    return CompanyProfile(
        linkedin_url=linkedin_url,
        logo_url=logo,
        tagline=tagline,
        about_text=None,
        follower_count=followers,
        employee_count_min=emin,
        employee_count_max=emax,
        employee_count_label=elabel,
    )
