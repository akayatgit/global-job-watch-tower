"""Shared posted-date helpers (search cards + job detail pages)."""

from __future__ import annotations

from datetime import date, datetime, timezone
import re

from app.scraper.parse import parse_relative_posted


def posted_date_from_detail(page, *, card_text: str | None = None) -> date | None:
    """Best-effort posted date from a job view page."""
    # <time datetime="YYYY-MM-DD">
    try:
        for t in page.css('time'):
            dt = t.attrib.get('datetime')
            if dt:
                try:
                    return datetime.strptime(dt[:10], '%Y-%m-%d').date()
                except ValueError:
                    pass
            rel = parse_relative_posted(' '.join(t.css('::text').getall()))
            if rel:
                return rel
    except Exception:
        pass

    for sel in (
        '.jobs-unified-top-card__posted-date',
        '.job-details-jobs-unified-top-card__tertiary-description-container',
        '.posted-time-ago__text',
        'span.tvm__text',
    ):
        try:
            text = ' '.join(page.css(f'{sel}::text').getall())
        except Exception:
            text = ''
        rel = parse_relative_posted(text)
        if rel:
            return rel

    if card_text:
        rel = parse_relative_posted(card_text)
        if rel:
            return rel

    try:
        blob = ' '.join(page.css('::text').getall())[:2500]
    except Exception:
        blob = ''
    # Prefer phrases near "ago" to avoid random numbers
    m = re.search(
        r'(?:posted|reposted)?\s*(just now|\d+\s*(?:minute|hour|day|week|month|year)s?\s+ago)',
        blob,
        re.I,
    )
    if m:
        return parse_relative_posted(m.group(0), now=datetime.now(timezone.utc))
    return parse_relative_posted(blob)
