"""Daily browser budget + idle gate for detail-page enrich (Plan B).

Discovery-first law (2026-08-08): search scrapes own the single browser
lane; per-job detail pages run only in idle, cool windows, within a fixed
daily page budget. The ledger lives in Redis (already a hard dependency as
the Celery broker) keyed per UTC day, and only the single `-c 1` worker
ever consumes from it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app import config

_KEY_PREFIX = 'detail_budget:'
_TTL_S = 48 * 3600  # let yesterday's key expire on its own


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _redis():
    import redis

    return redis.Redis.from_url(config.REDIS_URL)


def budget_key(day: date | None = None) -> str:
    d = day or utcnow().date()
    return f'{_KEY_PREFIX}{d.isoformat()}'


def used_today(client=None) -> int:
    """Detail pages fetched so far this UTC day (0 when Redis unreachable —
    if Redis is down the Celery worker is down too, so nothing consumes)."""
    try:
        client = client if client is not None else _redis()
        raw = client.get(budget_key())
        return int(raw or 0)
    except Exception:
        return 0


def remaining_today(client=None) -> int:
    return max(0, config.DETAIL_BUDGET_PER_DAY - used_today(client))


def consume_page(client=None) -> int:
    """Record one fetched detail page; returns pages used today."""
    try:
        client = client if client is not None else _redis()
        key = budget_key()
        used = int(client.incr(key))
        client.expire(key, _TTL_S)
        return used
    except Exception:
        return 0


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def next_search_due_at(db, *, now: datetime | None = None) -> datetime | None:
    """Earliest moment any enabled config cron or queued one-off wants the
    browser lane (same croniter math as ``enqueue_due_work``)."""
    from croniter import croniter

    from app.models import ScrapeRun, SearchConfig

    now = now or utcnow()
    due: list[datetime] = []
    for cfg in db.execute(
        select(SearchConfig).where(SearchConfig.enabled.is_(True))
    ).scalars():
        try:
            base = _aware(cfg.last_run_at or cfg.created_at or now)
            due.append(_aware(croniter(cfg.schedule_cron, base).get_next(datetime)))
        except Exception:
            continue
    for when in db.execute(
        select(ScrapeRun.scheduled_for).where(
            ScrapeRun.status == 'queued',
            ScrapeRun.run_type == 'one_off',
        )
    ).scalars():
        # NULL scheduled_for means the one-off is due immediately
        due.append(_aware(when) if when is not None else now)
    return min(due) if due else None


def trickle_gate(db, *, now: datetime | None = None) -> tuple[bool, str]:
    """May the light-mode detail trickle take the browser lane right now?

    Returns (ok, human reason). ALL conditions must hold: light mode,
    budget left, no active/queued search, no search due within the
    look-ahead, and the host fully Cool (details never add heat while
    Warm/Hot — searches keep absolute priority after cool-down).
    """
    from app import thermal
    from app.models import ScrapeRun
    from app.runtime_settings import get_detail_enrich_mode

    mode = get_detail_enrich_mode()
    if mode != 'light':
        return False, f'detail mode is {mode}'
    left = remaining_today()
    if left <= 0:
        return False, (
            f'daily detail budget spent ({config.DETAIL_BUDGET_PER_DAY} pages)'
        )
    active = db.execute(
        select(ScrapeRun.id).where(
            ScrapeRun.status.in_(('dispatched', 'running'))
        ).limit(1)
    ).scalar_one_or_none()
    if active is not None:
        return False, 'a search is running'
    now = now or utcnow()
    due = next_search_due_at(db, now=now)
    lookahead = timedelta(minutes=config.DETAIL_IDLE_LOOKAHEAD_MIN)
    if due is not None and due <= now + lookahead:
        return False, (
            f'a search is due within {config.DETAIL_IDLE_LOOKAHEAD_MIN} min'
        )
    snap = thermal.snapshot()
    if snap.level != 'cool':
        return False, f'heat is {snap.level} ({snap.detail})'
    return True, f'idle + cool · {left} detail page(s) left today'
