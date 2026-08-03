"""Enrich JobMaster rows with experience / degree / cert / domain requirements.

Opens LinkedIn job view pages in the same human-paced Chrome profile used
for search scrapes. Critical for employability graph clusters.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.console import console_log
from app.models import JobMaster
from app.models.models import utcnow
from app.runtime_settings import get_headless
from app.scraper.detail import parse_job_detail
from app.scraper.linkedin import dismiss_popups, human_delay
from app.scraper.session import sync_linkedin_session

logger = logging.getLogger(__name__)

LogFn = Callable[[str], None]


def _apply_requirements(job: JobMaster, detail) -> None:
    req = detail.requirements
    job.experience_min_years = req.experience_min_years
    job.experience_max_years = req.experience_max_years
    job.experience_label = req.experience_label
    job.experience_band = req.experience_band
    job.seniority_level = req.seniority_level or detail.seniority
    job.degrees = req.degrees or None
    job.certifications = req.certifications or None
    job.domains = req.domains or None
    job.description_text = req.description_text
    job.requirements_enriched_at = utcnow()


def pending_requirement_ids(db: Session, limit: int = 20) -> list[int]:
    rows = db.execute(
        select(JobMaster.id)
        .where(JobMaster.requirements_enriched_at.is_(None))
        .order_by(JobMaster.id.desc())
        .limit(max(1, min(limit, 40)))
    ).scalars().all()
    return list(rows)


def enrich_jobs_by_ids(
    db: Session,
    job_ids: list[int],
    *,
    run_id: int | None = None,
    log: LogFn | None = None,
) -> dict:
    """Visit each job view URL and fill requirement fields."""
    say = log or (lambda m: console_log('enrich', m, run_id=run_id))
    if not job_ids:
        return {'enriched': 0, 'failed': 0, 'skipped': 0}

    jobs = db.execute(
        select(JobMaster).where(JobMaster.id.in_(job_ids))
    ).scalars().all()
    by_id = {j.id: j for j in jobs}
    ordered = [by_id[i] for i in job_ids if i in by_id]
    if not ordered:
        return {'enriched': 0, 'failed': 0, 'skipped': len(job_ids)}

    say(f'Enriching requirements for {len(ordered)} job(s)…')
    sync = sync_linkedin_session()
    say(sync.detail)
    if not sync.cookies_ok:
        raise RuntimeError(sync.detail)

    from scrapling.fetchers import StealthySession

    enriched = 0
    failed = 0

    def settle(page):
        page.wait_for_timeout(int(random.uniform(1200, 2200)))
        dismiss_popups(page)
        # Expand “see more” on description when present
        for sel in (
            'button.jobs-description__footer-button',
            'button.show-more-less-html__button',
            'button[aria-label*="more"]',
        ):
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(int(random.uniform(400, 900)))
                    break
            except Exception:
                continue
        # Light human scroll on the detail pane
        for _ in range(random.randint(2, 4)):
            page.mouse.wheel(0, random.randint(200, 500))
            page.wait_for_timeout(int(random.uniform(250, 600)))
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
        for i, job in enumerate(ordered):
            url = job.job_url
            if not url:
                failed += 1
                continue
            if i > 0:
                waited = human_delay()
                say(f'Human wait {waited:.1f}s before next job detail…')
            say(f'Detail {i + 1}/{len(ordered)}: {job.title[:60]}')
            try:
                response = engine.fetch(url)
                detail = parse_job_detail(response, card_text=job.raw_text)
                _apply_requirements(job, detail)
                db.commit()
                enriched += 1
                bits = []
                if job.experience_band:
                    bits.append(job.experience_band)
                if job.degrees:
                    bits.append(f'{len(job.degrees)} degree(s)')
                if job.certifications:
                    bits.append(f'{len(job.certifications)} cert(s)')
                if job.domains:
                    bits.append(f'{len(job.domains)} domain(s)')
                say(
                    f'Stored requirements — {", ".join(bits) if bits else "parsed (sparse)"}'
                )
            except Exception as exc:
                db.rollback()
                failed += 1
                logger.exception('enrich failed job %s', job.id)
                say(f'Enrich failed for job #{job.id}: {str(exc)[:160]}')
                # Mark attempt so we don't spin forever on dead URLs
                try:
                    job = db.get(JobMaster, job.id)
                    if job:
                        job.requirements_enriched_at = utcnow()
                        job.experience_label = job.experience_label or 'enrich_failed'
                        db.commit()
                except Exception:
                    db.rollback()
            time.sleep(random.uniform(0.4, 1.1))

    say(f'Requirements enrich done: {enriched} ok, {failed} failed')
    return {'enriched': enriched, 'failed': failed, 'skipped': 0}
