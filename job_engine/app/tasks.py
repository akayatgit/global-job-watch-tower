from datetime import datetime, timedelta, timezone
import logging

from croniter import croniter
from sqlalchemy import desc, select

from app import config as app_config
from app.celery_app import celery
from app.cities import normalize_city
from app.console import console_log
from app.db import SessionLocal
from app.models import Company, ConsoleLog, JobMaster, RequestLog, ScrapeRun, SearchConfig
from app.relevance import filter_relevant
from app.scraper.linkedin import PageResult, TransientFetchError, scrape_search

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


def _get_or_create_company(db, name: str | None) -> Company | None:
    if not name:
        return None
    key = name.strip()
    company = db.execute(
        select(Company).where(Company.name == key)
    ).scalar_one_or_none()
    if company is None:
        company = Company(name=key)
        db.add(company)
        db.flush()
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

            # Keep only titles that actually match the searched role.
            # TODO: later, also store the rejected jobs so we can make use
            # of that data (adjacent-role analytics, model tuning, etc.)
            relevant, rejected = filter_relevant(page_result.jobs, cfg.keywords, run_id=run.id)
            rejected_total += len(rejected)

            page_inserted = 0
            for job in relevant:
                exists = db.execute(
                    select(JobMaster.id).where(
                        JobMaster.linkedin_job_id == job.linkedin_job_id
                    ).limit(1)
                ).scalar_one_or_none()
                if exists is not None:
                    continue
                company = _get_or_create_company(db, job.company)
                db.add(JobMaster(
                    linkedin_job_id=job.linkedin_job_id,
                    title=job.title,
                    company_id=company.id if company else None,
                    location=job.location,
                    city_key=normalize_city(job.location, job.title),
                    sector=cfg.sector,
                    job_url=job.job_url,
                    posted_date=job.posted_date,
                    raw_text=job.raw_text,
                    search_config_id=cfg.id,
                    scrape_run_id=run.id,
                ))
                inserted += 1
                page_inserted += 1
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
        return {
            'run_id': run.id,
            'status': final_status,
            'pages': run.pages_scraped,
            'found': found,
            'inserted': inserted,
            'rejected_by_ai': rejected_total,
        }
