"""Parse LinkedIn job detail / view pages for description + criteria."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

from app.scraper.company_page import CompanyProfile, company_bits_from_job_page
from app.scraper.posted import posted_date_from_detail
from app.scraper.requirements import JobRequirements, extract_requirements


@dataclass
class DetailParse:
    description: str
    seniority: str | None
    employment_type: str | None
    requirements: JobRequirements
    posted_date: date | None = None
    company: CompanyProfile | None = None


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    return ' '.join(value.split()).strip() or None


def _page_text_blob(page) -> str:
    try:
        chunks = page.css('::text').getall()
        return _clean(' '.join(chunks)) or ''
    except Exception:
        return ''


def parse_job_detail(page, *, card_text: str | None = None) -> DetailParse:
    """Extract description + seniority criteria from a job view response."""
    desc_parts: list[str] = []
    for sel in (
        '.jobs-description__content',
        '.jobs-box__html-content',
        '#job-details',
        '.description__text',
        'article.jobs-description',
        '.show-more-less-html__markup',
        '.jobs-description-content__text',
    ):
        try:
            parts = page.css(f'{sel} ::text').getall()
        except Exception:
            parts = []
        text = _clean(' '.join(parts))
        if text and len(text) > 80:
            desc_parts.append(text)
            break

    if not desc_parts:
        # Fallback: whole page text (still useful for regex extractors)
        blob = _page_text_blob(page)
        if blob:
            desc_parts.append(blob[:12000])

    description = desc_parts[0] if desc_parts else ''

    seniority = None
    employment_type = None
    try:
        items = page.css(
            'li.description__job-criteria-item, '
            'li.job-details-jobs-unified-top-card__job-insight'
        )
        for item in items:
            label = _clean(' '.join(item.css('h3::text, .t-bold::text').getall())) or ''
            value = _clean(
                ' '.join(
                    item.css(
                        'span::text, .description__job-criteria-text::text'
                    ).getall()
                )
            )
            if not value:
                continue
            low = label.lower()
            if 'seniority' in low:
                seniority = value
            elif 'employment' in low:
                employment_type = value
    except Exception:
        pass

    # Regex fallback for seniority in page text
    if not seniority:
        m = re.search(
            r'seniority\s*level\s*[:\-]?\s*'
            r'(internship|entry level|associate|mid-senior level|'
            r'senior|director|executive)',
            description + ' ' + _page_text_blob(page),
            re.I,
        )
        if m:
            seniority = m.group(1)

    req = extract_requirements(
        description,
        seniority=seniority,
        card_text=card_text,
    )
    company = company_bits_from_job_page(page)
    posted = posted_date_from_detail(page, card_text=card_text)
    return DetailParse(
        description=description,
        seniority=seniority,
        employment_type=employment_type,
        requirements=req,
        posted_date=posted,
        company=company,
    )
