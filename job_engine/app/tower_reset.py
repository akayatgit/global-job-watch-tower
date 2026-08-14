"""Base-level tower data reset (Ashok, 2026-08-14 meeting).

The broad role-keyword era collected everything; the MNC-first base wants a
clean rebuild. This wipes caught DATA and keeps every definition and every
guest-facing asset:

WIPED  — jobs, scrape runs (except in-flight rows, see below), request
         logs, and UNWATCHED companies (broad-catch leftovers).
KEPT   — search definitions (all of them, including sleeping role
         searches), watched companies + their profiles (the watchlist IS
         the product spine now), guests, alerts, chat history, waitlist,
         blocks, console/tower events.

In-flight safety: a running worker re-reads its run row before every page
(``current_status`` uses ``scalar_one`` — deleting the row would crash it).
Active runs are therefore CANCELLED gracefully and their rows kept; every
other run row is deleted.

Refill: clearing ``last_run_at`` makes every enabled search immediately due
(the beat computes due-ness from ``last_run_at or created_at``), so the
tower re-scrapes its whole catalogue one search at a time, heat-aware,
starting on the next beat tick — no empty tower waiting for tomorrow's
crons.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.models import Company, JobMaster, RequestLog, ScrapeRun, SearchConfig, TowerEvent

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ('queued', 'dispatched', 'running', 'cancel_requested')


def _active_runs(db) -> list[tuple[ScrapeRun, str]]:
    """Active runs joined to a human search name."""
    rows = db.execute(
        select(ScrapeRun, SearchConfig.name)
        .join(SearchConfig, SearchConfig.id == ScrapeRun.search_config_id)
        .where(ScrapeRun.status.in_(ACTIVE_STATUSES))
    ).all()
    return [(run, name) for run, name in rows]


def reset_preview(db) -> dict:
    """What a reset would wipe / keep / disturb — for the confirm message."""
    jobs = db.query(JobMaster).count()
    runs = db.query(ScrapeRun).count()
    request_logs = db.query(RequestLog).count()
    companies = db.query(Company).count()
    watched = db.query(Company).filter(Company.watched.is_(True)).count()
    enabled_searches = db.query(SearchConfig).filter(
        SearchConfig.enabled.is_(True)
    ).count()
    active = [name for _run, name in _active_runs(db)]
    return {
        'jobs': jobs,
        'runs': runs,
        'request_logs': request_logs,
        'companies': companies,
        'companies_watched_kept': watched,
        'companies_unwatched_wiped': companies - watched,
        'enabled_searches': enabled_searches,
        'active_searches': active,
    }


def reset_tower_data(db, *, purge_queue: bool = True) -> dict:
    """Execute the wipe. Cancels active runs gracefully, keeps their rows."""
    preview = reset_preview(db)

    cancelled: list[str] = []
    keep_run_ids: set[int] = set()
    for run, name in _active_runs(db):
        keep_run_ids.add(run.id)
        cancelled.append(name)
        # queued/dispatched stop immediately; a running worker checks status
        # before every page and stops gracefully on any STOP status.
        run.status = 'cancelled' if run.status in ('queued', 'dispatched') else 'cancel_requested'
        run.error = 'cancelled for tower data reset'

    db.query(RequestLog).delete(synchronize_session=False)
    db.query(JobMaster).delete(synchronize_session=False)
    if keep_run_ids:
        db.query(ScrapeRun).filter(
            ScrapeRun.id.notin_(keep_run_ids)
        ).delete(synchronize_session=False)
    else:
        db.query(ScrapeRun).delete(synchronize_session=False)
    db.query(Company).filter(
        Company.watched.is_(False)
    ).delete(synchronize_session=False)
    for cfg in db.execute(select(SearchConfig)).scalars():
        cfg.last_run_at = None
    db.add(TowerEvent(
        kind='tower_reset',
        detail=(
            f"wiped {preview['jobs']} jobs · "
            f"{preview['companies_unwatched_wiped']} unwatched companies · "
            f"{preview['runs']} runs; cancelled {len(cancelled)} active; "
            f"{preview['enabled_searches']} searches rescheduled"
        )[:1000],
    ))
    db.commit()

    # Drop queued Celery messages so pre-reset runs don't resurrect.
    if purge_queue:
        try:
            from app.celery_app import celery as celery_app
            celery_app.control.purge()
        except Exception:  # best-effort: reset must not fail on broker hiccups
            logger.warning('celery purge after tower reset failed', exc_info=True)

    return {
        **preview,
        'cancelled_active': cancelled,
        'done': True,
    }
