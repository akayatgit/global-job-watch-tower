from datetime import datetime, timedelta, timezone
import logging

from celery.signals import worker_ready
from croniter import croniter
from sqlalchemy import desc, select

from app import config as app_config
from app.celery_app import celery
from app.cities import normalize_city
from app.console import console_log
from app.db import SessionLocal
from app.mnc_watchlist import company_matches_target
from app.models import Company, ConsoleLog, JobMaster, RequestLog, ScrapeRun, SearchConfig
from app.relevance import filter_relevant
from app.runtime_settings import get_detail_enrich_mode
from app.scraper.linkedin import PageResult, TransientFetchError, scrape_search
from app.scraper.requirements import JobRequirements, extract_requirements
from app.seniority import FRESHER_TRACK_SILENCE_LABEL, title_seniority_veto

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ('queued', 'dispatched', 'running')
STOP_STATUSES = ('cancelled', 'cancel_requested')
RETRYABLE_MARKERS = (
    'timeout', 'timed out', 'temporar', 'connection', 'reset by peer',
    'http 500', 'http 502', 'http 503', 'http 504',
    'fetch failed', 'failed after', 'network',
)
NON_RETRYABLE_MARKERS = (
    'login page',
    'linkedin_block',
    'no linkedin cookies',
    'search config deleted',
    'source chrome profile missing',
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def card_requirements(
    raw_text: str | None,
    track: str | None,
    title: str | None = None,
) -> tuple[JobRequirements, str | None, str | None]:
    """Browser-free requirements from the search-card text (Plan B).

    Returns (requirements, experience_band, experience_label). Fresher-track
    cards with no stated band are stamped 'Fresher' from LinkedIn's own
    f_E=1,2 (Internship + Entry) search filter — but only when the TITLE
    carries no seniority signal. Live incident (2026-08-14): "Omniverse –
    Software Engineer II" (detail page: Bachelor's + 3–6 years) got the
    Fresher stamp because LinkedIn's Entry tag lied and nothing read the
    title. A vetoed title stays band-NULL, marked pending verification, and
    is excluded from fresher results until the detail page states the real
    years. Stated card years always win (unchanged law).
    ``requirements_enriched_at`` is NOT set by this path: the job stays
    pending for description-level enrich (degrees/certs/domains).
    """
    req = extract_requirements('', card_text=raw_text or '')
    band = req.experience_band
    label = req.experience_label
    if (track or '') == 'fresher' and not band:
        if title_seniority_veto(title):
            label = label or 'Seniority in title — pending verification'
        else:
            band = 'Fresher'
            label = label or FRESHER_TRACK_SILENCE_LABEL
    return req, band, label


def _get_or_create_company(
    db,
    name: str | None,
    *,
    linkedin_url: str | None = None,
    logo_url: str | None = None,
) -> Company | None:
    if not name:
        return None
    key = name.strip()
    company = db.execute(
        select(Company).where(Company.name == key)
    ).scalar_one_or_none()
    if company is None:
        company = Company(
            name=key,
            linkedin_url=linkedin_url,
            logo_url=logo_url,
        )
        db.add(company)
        db.flush()
    else:
        if linkedin_url and not company.linkedin_url:
            company.linkedin_url = linkedin_url
        if logo_url and not company.logo_url:
            company.logo_url = logo_url
    return company


def _reap_stale_runs(db, now: datetime, *, minutes: int | None = None,
                     reason: str | None = None) -> int:
    """Mark runs stuck in running/dispatched after a worker crash as failed."""
    mins = minutes if minutes is not None else app_config.STALE_RUN_MINUTES
    cutoff = now - timedelta(minutes=mins)
    stale = db.execute(
        select(ScrapeRun).where(
            ScrapeRun.status.in_(('running', 'dispatched', 'cancel_requested')),
            ScrapeRun.started_at.is_not(None),
            ScrapeRun.started_at < cutoff,
        )
    ).scalars().all()
    why = reason or (
        f'Stale run reaped after {mins} minutes '
        'with no finish (worker likely restarted).'
    )
    for run in stale:
        run.status = 'failed'
        run.error = why[:2000]
        run.finished_at = now
        console_log('worker', f'Run #{run.id} reaped as stale/failed.',
                    run_id=run.id, level='warn')
    if stale:
        db.commit()
    return len(stale)


def _reap_zombie_runs(db, now: datetime) -> int:
    """Fail running scrapes with no console activity (browser/worker died quietly)."""
    # A healthy page dwell logs every ~30–45s; 12 quiet minutes = dead.
    quiet_after = now - timedelta(minutes=12)
    started_before = now - timedelta(minutes=15)
    candidates = db.execute(
        select(ScrapeRun).where(
            ScrapeRun.status.in_(('running', 'dispatched')),
            ScrapeRun.started_at.is_not(None),
            ScrapeRun.started_at < started_before,
        )
    ).scalars().all()
    reaped = 0
    for run in candidates:
        last = db.execute(
            select(ConsoleLog.ts).where(ConsoleLog.run_id == run.id)
            .order_by(desc(ConsoleLog.id)).limit(1)
        ).scalar_one_or_none()
        last_ts = last or run.started_at
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        if last_ts > quiet_after:
            continue
        run.status = 'failed'
        run.error = (
            'Zombie run reaped — no live-feed activity for 12+ minutes '
            '(browser/worker likely died; was blocking the search queue).'
        )[:2000]
        run.finished_at = now
        console_log(
            'worker',
            f'Run #{run.id} reaped as zombie (silent too long).',
            run_id=run.id, level='warn',
        )
        reaped += 1
    if reaped:
        db.commit()
    return reaped


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc).lower()
    if any(marker in msg for marker in NON_RETRYABLE_MARKERS):
        return False
    if isinstance(exc, TransientFetchError):
        return True
    return any(marker in msg for marker in RETRYABLE_MARKERS)


@celery.task(name='app.tasks.enqueue_due_work')
def enqueue_due_work():
    """Beat task: dispatch due recurring configs and due one-off runs."""
    from app import thermal

    now = utcnow()
    dispatched = 0
    with SessionLocal() as db:
        # Keep the console feed from growing forever
        db.query(ConsoleLog).filter(ConsoleLog.ts < now - timedelta(days=3)).delete()
        db.commit()
        _reap_stale_runs(db, now)
        _reap_zombie_runs(db, now)

        # Heat-aware beat: when hot, skip starting new scrapes this tick so
        # Ollama + Chrome can cool (matches Ashok's "save the heat" mandate).
        ok_to_scrape, heat = thermal.allow_new_scrape()
        if not ok_to_scrape:
            console_log(
                'beat',
                f'Heat pause — no new scrapes ({heat.level}: {heat.detail}). '
                f'Next beat will re-check after cool-down.',
                level='warn',
            )
            return {'dispatched': 0, 'heat': heat.level, 'paused': True}

        # 1. One-off runs whose time has come
        one_offs = db.execute(
            select(ScrapeRun).where(
                ScrapeRun.status == 'queued',
                ScrapeRun.run_type == 'one_off',
            )
        ).scalars().all()
        for run in one_offs:
            when = run.scheduled_for
            if when is not None and when.replace(tzinfo=when.tzinfo or timezone.utc) > now:
                continue
            if _config_busy(db, run.search_config_id, exclude_run_id=run.id):
                continue
            run.status = 'dispatched'
            db.commit()
            run_scrape.delay(run.id)
            dispatched += 1

        # 2. Recurring configs due per cron — at most ONE per beat tick.
        # With 100 daily searches and human dwell, flooding the queue would
        # stack hours of work; one-at-a-time keeps the tower reliable.
        configs = db.execute(
            select(SearchConfig).where(SearchConfig.enabled.is_(True))
            .order_by(SearchConfig.priority.asc(), SearchConfig.id.asc())
        ).scalars().all()
        for cfg in configs:
            try:
                base = cfg.last_run_at or cfg.created_at
                if base.tzinfo is None:
                    base = base.replace(tzinfo=timezone.utc)
                next_due = croniter(cfg.schedule_cron, base).get_next(datetime)
            except (ValueError, KeyError) as exc:
                logger.warning('config %s has bad cron %r: %s', cfg.id, cfg.schedule_cron, exc)
                continue
            if next_due > now:
                continue
            if _config_busy(db, cfg.id):
                continue
            # Global busy: don't stack a new scheduled scrape while any run works
            any_busy = db.execute(
                select(ScrapeRun.id).where(
                    ScrapeRun.status.in_(('dispatched', 'running'))
                ).limit(1)
            ).scalar_one_or_none()
            if any_busy is not None:
                break
            run = ScrapeRun(
                search_config_id=cfg.id,
                run_type='scheduled',
                status='dispatched',
                target_date=now.date(),
            )
            cfg.last_run_at = now
            db.add(run)
            db.commit()
            run_scrape.delay(run.id)
            dispatched += 1
            break  # one scheduled dispatch per beat scan

    return {'dispatched': dispatched}


def _config_busy(db, config_id: int, exclude_run_id: int | None = None) -> bool:
    query = select(ScrapeRun.id).where(
        ScrapeRun.search_config_id == config_id,
        ScrapeRun.status.in_(('dispatched', 'running')),
    )
    if exclude_run_id is not None:
        query = query.where(ScrapeRun.id != exclude_run_id)
    return db.execute(query.limit(1)).scalar_one_or_none() is not None


@celery.task(name='app.tasks.run_scrape', bind=True, max_retries=2, default_retry_delay=300)
def run_scrape(self, scrape_run_id: int):
    """Execute one scrape run: browser session, pagination, dedup inserts."""
    with SessionLocal() as db:
        run = db.get(ScrapeRun, scrape_run_id)
        if run is None:
            return {'error': 'run not found'}
        if run.status == 'cancelled':
            return {'skipped': 'cancelled'}
        cfg = db.get(SearchConfig, run.search_config_id)
        if cfg is None:
            run.status = 'failed'
            run.error = 'search config deleted'
            db.commit()
            return {'error': 'config deleted'}

        run.status = 'running'
        run.started_at = utcnow()
        run.error = None
        db.commit()
        effective_pages = max(1, min(cfg.max_pages, app_config.MAX_PAGES))
        console_log('worker', f'Run #{run.id} started: "{cfg.keywords}" '
                              f'({cfg.location_label or cfg.geo_id}), up to {effective_pages} page(s).',
                    run_id=run.id)

        found = 0
        inserted = 0
        rejected_total = 0
        new_job_ids: list[int] = []

        def current_status() -> str:
            return db.execute(
                select(ScrapeRun.status).where(ScrapeRun.id == run.id)
            ).scalar_one()

        def should_continue() -> bool:
            # Admin "Stop" sets cancel_requested; checked before every page
            return current_status() not in STOP_STATUSES

        def on_page(page_result: PageResult):
            nonlocal found, inserted, rejected_total
            run.pages_scraped = page_result.page_num
            run.last_request_at = utcnow()
            db.add(RequestLog(
                scrape_run_id=run.id,
                page_num=page_result.page_num,
                url=page_result.url,
                http_status=page_result.http_status,
            ))
            found += len(page_result.jobs)
            db.commit()  # persist page progress even while AI filter runs

            page_inserted = 0
            already_saved: set[str] = set()

            def persist_kept(kept_jobs):
                """Write kept jobs to DB immediately after each AI batch."""
                nonlocal inserted, page_inserted
                n_new = 0
                for job in kept_jobs:
                    if job.linkedin_job_id in already_saved:
                        continue
                    exists = db.execute(
                        select(JobMaster.id).where(
                            JobMaster.linkedin_job_id == job.linkedin_job_id
                        ).limit(1)
                    ).scalar_one_or_none()
                    if exists is not None:
                        already_saved.add(job.linkedin_job_id)
                        continue
                    company = _get_or_create_company(
                        db,
                        job.company,
                        linkedin_url=getattr(job, 'company_linkedin_url', None),
                        logo_url=getattr(job, 'company_logo_url', None),
                    )
                    # Card-first requirements (Plan B): free extraction from
                    # the card text so experience data exists even before any
                    # detail page is ever visited.
                    req, band, exp_label = card_requirements(
                        job.raw_text, cfg.track, title=job.title,
                    )
                    row = JobMaster(
                        linkedin_job_id=job.linkedin_job_id,
                        title=job.title,
                        company_id=company.id if company else None,
                        location=job.location,
                        city_key=normalize_city(job.location, job.title),
                        sector=cfg.sector,
                        job_url=job.job_url,
                        posted_date=job.posted_date,
                        raw_text=job.raw_text,
                        source_track=cfg.track,
                        search_config_id=cfg.id,
                        scrape_run_id=run.id,
                        experience_min_years=req.experience_min_years,
                        experience_max_years=req.experience_max_years,
                        experience_label=exp_label,
                        experience_band=band,
                        seniority_level=req.seniority_level,
                    )
                    db.add(row)
                    db.flush()
                    new_job_ids.append(row.id)
                    already_saved.add(job.linkedin_job_id)
                    inserted += 1
                    page_inserted += 1
                    n_new += 1
                run.jobs_found = found
                run.jobs_inserted = inserted
                # If admin cancelled mid-filter, still keep jobs we already judged
                if current_status() == 'cancelled':
                    run.status = 'running'
                db.commit()
                if n_new:
                    console_log(
                        'worker',
                        f'Run #{run.id}: stored {n_new} job(s) from this AI batch '
                        f'(page {page_result.page_num} total stored {page_inserted}).',
                        run_id=run.id,
                    )

            target = (getattr(cfg, 'target_company', None) or '').strip()
            if target:
                # MNC-first company search (2026-08-14): the company match IS
                # the relevance — keep EVERY role at the target company,
                # reject everything else, and skip the AI filter entirely
                # (deterministic precision, zero Ollama heat).
                relevant = [
                    job for job in page_result.jobs
                    if company_matches_target(job.company, target)
                ]
                rejected_total += len(page_result.jobs) - len(relevant)
                persist_kept(relevant)
            else:
                # Keep only titles that actually match the searched role.
                # Persist after each batch so the Jobs panel is not empty for 10+ min.
                relevant, rejected = filter_relevant(
                    page_result.jobs, cfg.keywords, run_id=run.id, on_kept=persist_kept,
                )
                rejected_total += len(rejected)
                # Safety net for any kept rows the callback missed (e.g. keyword path)
                persist_kept(relevant)
            run.jobs_found = found
            run.jobs_inserted = inserted
            db.commit()
            dupes = len(relevant) - page_inserted
            console_log('worker', f'Run #{run.id} page {page_result.page_num}: '
                                  f'{len(page_result.jobs)} card(s) → {len(relevant)} relevant, '
                                  f'{dupes} already in DB, {page_inserted} newly stored. '
                                  f'Totals: {found} seen, {inserted} stored.',
                        run_id=run.id)

        try:
            scrape_search(
                keywords=cfg.keywords,
                geo_id=cfg.geo_id,
                max_pages=cfg.max_pages,
                on_page=on_page,
                should_continue=should_continue,
                log=lambda msg: console_log('scraper', msg, run_id=run.id),
                run_id=run.id,
                experience_filter=getattr(cfg, 'experience_filter', None),
            )
        except Exception as exc:
            db.rollback()
            run = db.get(ScrapeRun, scrape_run_id)
            err = str(exc)[:2000]
            logger.exception('scrape run %s failed', scrape_run_id)
            console_log('worker', f'Run #{run.id} FAILED: {err[:300]}',
                        run_id=run.id, level='error')

            # Transient network/fetch errors: Celery retry (same run id)
            if _is_retryable(exc) and self.request.retries < self.max_retries:
                run.status = 'dispatched'
                run.error = f'Transient failure, retrying: {err}'[:2000]
                run.finished_at = None
                db.commit()
                console_log(
                    'worker',
                    f'Run #{run.id}: transient error — Celery will retry '
                    f'({self.request.retries + 1}/{self.max_retries}).',
                    run_id=run.id, level='warn',
                )
                raise self.retry(exc=exc, countdown=max(60, int(app_config.MIN_DELAY_S * 8)))

            run.status = 'failed'
            run.error = err
            run.finished_at = utcnow()
            db.commit()
            return {'run_id': run.id, 'status': 'failed', 'error': run.error}

        final_status = 'cancelled' if current_status() in STOP_STATUSES else 'success'
        run.status = final_status
        run.finished_at = utcnow()
        db.commit()
        console_log('worker', f'Run #{run.id} {final_status}: {run.pages_scraped} page(s), '
                              f'{found} seen, {inserted} stored, {rejected_total} rejected by AI.',
                    run_id=run.id)
        # Detail-page requirements enrich: only 'full' (legacy) mode queues
        # the post-run burst. Plan B (light/off) leaves jobs pending — the
        # idle-gated trickle / a later re-enable picks them up. Discovery
        # owns the browser lane.
        detail_mode = get_detail_enrich_mode()
        if final_status == 'success' and new_job_ids and detail_mode == 'full':
            try:
                enrich_job_requirements.delay(
                    job_ids=new_job_ids[:40],
                    run_id=run.id,
                )
                console_log(
                    'worker',
                    f'Run #{run.id}: queued requirements enrich for '
                    f'{min(len(new_job_ids), 40)} new job(s).',
                    run_id=run.id,
                )
            except Exception as exc:
                console_log(
                    'worker',
                    f'Run #{run.id}: could not queue enrich — {str(exc)[:160]}',
                    run_id=run.id, level='warn',
                )
        elif final_status == 'success' and new_job_ids:
            console_log(
                'worker',
                f'Run #{run.id}: detail enrich deferred ({detail_mode} mode, '
                f'discovery-first) — {len(new_job_ids)} job(s) stay pending '
                f'for the idle trickle.',
                run_id=run.id,
            )
        if final_status == 'success' and new_job_ids:
            # Company logos / followers / punchlines (dedupe ids from new jobs)
            try:
                co_ids = db.execute(
                    select(JobMaster.company_id)
                    .where(
                        JobMaster.id.in_(new_job_ids[:80]),
                        JobMaster.company_id.is_not(None),
                    )
                    .distinct()
                ).scalars().all()
                co_ids = [int(x) for x in co_ids if x]
                if co_ids:
                    enrich_company_profiles.delay(
                        company_ids=co_ids[:12],
                        run_id=run.id,
                    )
                    console_log(
                        'worker',
                        f'Run #{run.id}: queued company profile enrich for '
                        f'{min(len(co_ids), 12)} company(ies).',
                        run_id=run.id,
                    )
            except Exception as exc:
                console_log(
                    'worker',
                    f'Run #{run.id}: could not queue company enrich — {str(exc)[:160]}',
                    run_id=run.id, level='warn',
                )
        return {
            'run_id': run.id,
            'status': final_status,
            'pages': run.pages_scraped,
            'found': found,
            'inserted': inserted,
            'rejected_by_ai': rejected_total,
            'enrich_queued': (
                len(new_job_ids[:40])
                if final_status == 'success' and detail_mode == 'full' else 0
            ),
            'detail_mode': detail_mode,
        }


@celery.task(name='app.tasks.enrich_job_requirements', bind=True, max_retries=1)
def enrich_job_requirements(self, job_ids: list[int] | None = None, run_id: int | None = None):
    """Open LinkedIn job views and store experience / degree / cert / domain."""
    from app import detail_budget
    from app.enrichment import enrich_jobs_by_ids, pending_requirement_ids

    mode = get_detail_enrich_mode()
    if mode == 'off':
        # Also swallows stale tasks queued before a mode flip
        return {'enriched': 0, 'paused': True, 'mode': 'off'}
    batch_cap = 12
    if mode == 'light':
        left = detail_budget.remaining_today()
        if left <= 0:
            return {
                'enriched': 0,
                'skipped': 'daily detail budget exhausted',
                'mode': 'light',
            }
        batch_cap = min(left, app_config.DETAIL_BATCH_SIZE)

    with SessionLocal() as db:
        ids = list(job_ids or [])
        if ids and mode == 'light':
            ids = ids[:batch_cap]
        if not ids:
            ids = pending_requirement_ids(db, limit=batch_cap)
        if not ids:
            return {'enriched': 0, 'note': 'nothing pending'}
        try:
            return enrich_jobs_by_ids(
                db, ids, run_id=run_id,
                log=lambda msg: console_log('enrich', msg, run_id=run_id),
            )
        except Exception as exc:
            logger.exception('enrich_job_requirements failed')
            console_log(
                'enrich', f'Requirements enrich FAILED: {str(exc)[:240]}',
                run_id=run_id, level='error',
            )
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc, countdown=120)
            return {'error': str(exc)[:500]}


def should_chain_backfill(db, result) -> tuple[bool, str]:
    """Full-mode drain (Ashok, 2026-08-14): after a verification batch, may
    the next one start right away instead of waiting for the 10-min beat?

    Chain only while it is safe AND useful: the last batch actually
    verified something (never hot-loop on an empty or failing queue),
    jobs are still pending, the scrape lane is free (scraping always
    wins), and the host is not Hot/Critical.
    """
    from app import thermal
    from app.enrichment import pending_requirement_ids

    enriched = result.get('enriched', 0) if isinstance(result, dict) else 0
    if not enriched:
        return False, 'last batch verified nothing'
    if not pending_requirement_ids(db, limit=1):
        return False, 'verification queue drained'
    active = db.execute(
        select(ScrapeRun.id).where(
            ScrapeRun.status.in_(('queued', 'dispatched', 'running'))
        ).limit(1)
    ).scalar_one_or_none()
    if active is not None:
        return False, 'scrape lane busy — beat resumes the drain later'
    snap = thermal.snapshot()
    if snap.level in ('hot', 'critical'):
        return False, f'host too hot ({snap.level})'
    return True, 'jobs still waiting, lane free'


@celery.task(name='app.tasks.enrich_pending_requirements')
def enrich_pending_requirements():
    """Beat: budgeted, idle-gated backfill of requirement details (Plan B).

    off   → no-op (jobs stay pending, resumable).
    light → runs a small batch only when the trickle gate says the browser
            lane is truly free: budget left, no run active/queued, no search
            due within the look-ahead, host Cool.
    full  → drains: one batch per task, then self-requeues while jobs are
            pending and the lane is free (queued scrapes interleave — FIFO
            keeps scraping first). No more waiting out the 10-min bell with
            a backlog standing in line.
    """
    from app import detail_budget

    mode = get_detail_enrich_mode()
    if mode == 'off':
        return {'paused': True, 'mode': 'off'}
    if mode == 'light':
        with SessionLocal() as db:
            ok, reason = detail_budget.trickle_gate(db)
        if not ok:
            return {'skipped': reason, 'mode': 'light'}
        console_log('enrich', f'Detail trickle window open — {reason}.')
    result = enrich_job_requirements(job_ids=None, run_id=None)
    if mode == 'full':
        try:
            with SessionLocal() as db:
                chain, reason = should_chain_backfill(db, result)
            if chain:
                enrich_pending_requirements.apply_async(countdown=5)
                console_log(
                    'enrich',
                    f'Verification drain continues — {reason}; '
                    'next batch in 5s.',
                )
            else:
                console_log('enrich', f'Verification drain pauses — {reason}.')
        except Exception:
            logger.warning('backfill chain check failed', exc_info=True)
    return result


@worker_ready.connect
def _kick_detail_drain(**_kwargs):
    """Start the full-mode verification drain right after a worker boot.

    Deploys purge queued enrich tasks (2026-08-14 incident: the Accenture
    '5 years' job sat unverified because the deploy purge ate its queued
    burst) — kicking one backfill on worker_ready means the drain resumes
    seconds after every restart instead of waiting out the first 10-min
    beat tick.
    """
    try:
        if get_detail_enrich_mode() == 'full':
            enrich_pending_requirements.apply_async(countdown=10)
    except Exception:
        logger.warning('detail drain kickoff failed', exc_info=True)


@celery.task(name='app.tasks.enrich_company_profiles', bind=True, max_retries=1)
def enrich_company_profiles(self, company_ids: list[int] | None = None, run_id: int | None = None):
    """Visit LinkedIn company pages for logo / followers / size / punchline."""
    from app.company_enrichment import enrich_companies_by_ids, pending_company_ids

    with SessionLocal() as db:
        ids = list(company_ids or [])
        if not ids:
            ids = pending_company_ids(db, limit=6)
        if not ids:
            return {'enriched': 0, 'note': 'nothing pending'}
        try:
            return enrich_companies_by_ids(
                db, ids, run_id=run_id,
                log=lambda msg: console_log('company', msg, run_id=run_id),
            )
        except Exception as exc:
            logger.exception('enrich_company_profiles failed')
            console_log(
                'company', f'Company enrich FAILED: {str(exc)[:240]}',
                run_id=run_id, level='error',
            )
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc, countdown=180)
            return {'error': str(exc)[:500]}


@celery.task(name='app.tasks.enrich_pending_companies')
def enrich_pending_companies():
    """Beat: backfill company logos / followers / punchlines (after job scrapes)."""
    return enrich_company_profiles(company_ids=None, run_id=None)
