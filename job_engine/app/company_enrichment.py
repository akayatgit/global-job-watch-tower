"""Enrich Company rows with logo, tagline, followers, size, casual punchline.

Uses the same human-paced Chrome profile as job scrapes. Punchline is a
casual one-liner for freshers (Ollama when cool; otherwise tagline/about).
"""

from __future__ import annotations

import logging
import random
import time
from typing import Callable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import config
from app.console import console_log
from app.models import Company
from app.models.models import utcnow
from app.runtime_settings import get_headless
from app.scraper.company_page import CompanyProfile, parse_company_page
from app.scraper.linkedin import dismiss_popups, human_delay
from app.scraper.session import sync_linkedin_session

logger = logging.getLogger(__name__)
LogFn = Callable[[str], None]


def _apply_profile(company: Company, profile: CompanyProfile, *, partial: bool = False) -> bool:
    """Merge non-empty profile fields onto company. Returns True if anything changed."""
    changed = False

    def set_if(attr: str, value):
        nonlocal changed
        if value is None or value == '':
            return
        if getattr(company, attr) != value:
            setattr(company, attr, value)
            changed = True

    set_if('linkedin_url', profile.linkedin_url)
    set_if('logo_url', profile.logo_url)
    set_if('tagline', (profile.tagline or '')[:400] or None)
    set_if('about_text', profile.about_text)
    set_if('follower_count', profile.follower_count)
    set_if('employee_count_min', profile.employee_count_min)
    set_if('employee_count_max', profile.employee_count_max)
    set_if('employee_count_label', profile.employee_count_label)
    if not partial and (
        profile.logo_url or profile.follower_count or profile.tagline or profile.about_text
    ):
        company.profile_enriched_at = utcnow()
        changed = True
    return changed


def apply_job_page_company_bits(company: Company, profile: CompanyProfile) -> bool:
    """Lighter merge from job detail (does not stamp full profile_enriched_at)."""
    return _apply_profile(company, profile, partial=True)


def pending_company_ids(db: Session, limit: int = 8) -> list[int]:
    """Companies with a LinkedIn URL still missing logo / followers / punchline."""
    rows = db.execute(
        select(Company.id)
        .where(
            Company.linkedin_url.is_not(None),
            or_(
                Company.profile_enriched_at.is_(None),
                Company.logo_url.is_(None),
                Company.follower_count.is_(None),
                Company.punchline.is_(None),
            ),
        )
        .order_by(Company.id.desc())
        .limit(max(1, min(limit, 15)))
    ).scalars().all()
    return list(rows)


def craft_punchline_local(company: Company) -> str | None:
    """Fallback casual one-liner without calling Ollama."""
    name = (company.name or 'This team').strip()
    tag = (company.tagline or '').strip()
    about = (company.about_text or '').strip()
    if tag and len(tag) <= 160:
        # Soft casual wrap if tagline is corporate
        if tag.lower().startswith(name.lower()):
            return tag[:400]
        return f'{tag} — solid place for a fresher to grow.'[:400]
    if about:
        # First sentence-ish
        chunk = about.split('.')[0].strip()
        if 20 <= len(chunk) <= 180:
            return f'{chunk}. Good runway if you want real work early.'[:400]
        return about[:180].rstrip() + '…'
    return None


def craft_punchline_ollama(company: Company) -> str | None:
    """Casual why-join line via local Ollama when thermal allows."""
    try:
        from app.thermal import ollama_path_open
        if not ollama_path_open():
            return None
    except Exception:
        return None

    tag = company.tagline or ''
    about = (company.about_text or '')[:700]
    if not tag and not about:
        return None
    prompt = (
        f'Company: {company.name}\n'
        f'Tagline: {tag}\n'
        f'About: {about}\n\n'
        'Write ONE casual sentence (max 22 words) for a fresh graduate: '
        'what they do and why joining could be exciting. No hashtags, '
        'no quotes, no emojis.'
    )
    try:
        import httpx
        r = httpx.post(
            'http://127.0.0.1:11434/api/chat',
            json={
                'model': config.OLLAMA_MODEL,
                'stream': False,
                'messages': [
                    {
                        'role': 'system',
                        'content': 'You write short casual recruiting one-liners.',
                    },
                    {'role': 'user', 'content': prompt},
                ],
                'options': {'temperature': 0.6, 'num_predict': 60},
            },
            timeout=min(45.0, config.OLLAMA_TIMEOUT_S),
        )
        r.raise_for_status()
        content = (r.json().get('message') or {}).get('content') or ''
        line = ' '.join(content.split()).strip().strip('"\'')
        if 12 <= len(line) <= 400:
            return line
    except Exception as exc:
        logger.info('punchline ollama skipped: %s', exc)
    return None


def ensure_punchline(company: Company) -> bool:
    if company.punchline:
        return False
    line = craft_punchline_ollama(company) or craft_punchline_local(company)
    if not line:
        return False
    company.punchline = line[:400]
    return True


def enrich_companies_by_ids(
    db: Session,
    company_ids: list[int],
    *,
    run_id: int | None = None,
    log: LogFn | None = None,
) -> dict:
    say = log or (lambda m: console_log('company', m, run_id=run_id))
    if not company_ids:
        return {'enriched': 0, 'failed': 0, 'skipped': 0}

    companies = db.execute(
        select(Company).where(Company.id.in_(company_ids))
    ).scalars().all()
    by_id = {c.id: c for c in companies}
    ordered = [by_id[i] for i in company_ids if i in by_id and by_id[i].linkedin_url]
    if not ordered:
        return {'enriched': 0, 'failed': 0, 'skipped': len(company_ids)}

    say(f'Enriching company profiles for {len(ordered)} company(ies)…')
    sync = sync_linkedin_session()
    say(sync.detail)
    if not sync.cookies_ok:
        raise RuntimeError(sync.detail)

    from scrapling.fetchers import StealthySession

    enriched = failed = 0

    def settle(page):
        page.wait_for_timeout(int(random.uniform(1400, 2400)))
        dismiss_popups(page)
        for _ in range(random.randint(2, 4)):
            page.mouse.wheel(0, random.randint(220, 520))
            page.wait_for_timeout(int(random.uniform(280, 700)))
        dismiss_popups(page)
        return page

    session_kwargs = dict(
        headless=get_headless(),
        real_chrome=True,
        user_data_dir=str(config.CHROME_BOT_PROFILE),
        network_idle=False,
        timeout=90000,
        wait=800,
        page_action=settle,
        google_search=False,
    )

    with StealthySession(**session_kwargs) as engine:
        for i, company in enumerate(ordered):
            url = company.linkedin_url
            if not url:
                failed += 1
                continue
            # Prefer /about/ for size + about text
            about_url = url.rstrip('/') + '/about/'
            if i > 0:
                waited = human_delay()
                say(f'Human wait {waited:.1f}s before next company…')
            say(f'Company {i + 1}/{len(ordered)}: {company.name[:60]}')
            try:
                response = engine.fetch(about_url)
                profile = parse_company_page(response, page_url=about_url)
                if not profile.logo_url and not profile.follower_count:
                    # Fallback to main company page
                    response = engine.fetch(url)
                    profile = parse_company_page(response, page_url=url)
                _apply_profile(company, profile, partial=False)
                ensure_punchline(company)
                db.commit()
                enriched += 1
                bits = []
                if company.logo_url:
                    bits.append('logo')
                if company.follower_count is not None:
                    bits.append(f'{company.follower_count:,} followers')
                if company.employee_count_label:
                    bits.append(company.employee_count_label)
                if company.punchline:
                    bits.append('punchline')
                say(f'Stored company profile — {", ".join(bits) if bits else "sparse"}')
            except Exception as exc:
                db.rollback()
                failed += 1
                logger.exception('company enrich failed %s', company.id)
                say(f'Company enrich failed #{company.id}: {str(exc)[:160]}')
                try:
                    company = db.get(Company, company.id)
                    if company:
                        company.profile_enriched_at = utcnow()
                        db.commit()
                except Exception:
                    db.rollback()
            time.sleep(random.uniform(0.4, 1.1))

    say(f'Company enrich done: {enriched} ok, {failed} failed')
    return {'enriched': enriched, 'failed': failed, 'skipped': 0}
