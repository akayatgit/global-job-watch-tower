"""Tower Health vitals — host + scrape pulse for header and /health page.

Keyword filter is Plan B only (critical heat / no GPU). Ollama is the path
that keeps relevance data trustworthy while we learn this laptop's capacity.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app import config, thermal
from app.models import ScrapeRun, SearchConfig, TowerEvent


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def record_event(db: Session, kind: str, run_id: int | None = None,
                 detail: str = '') -> None:
    db.add(TowerEvent(kind=kind, run_id=run_id, detail=(detail or '')[:1000]))
    db.commit()


def record_event_standalone(kind: str, run_id: int | None = None,
                            detail: str = '') -> None:
    """Safe write from scraper/worker (own session)."""
    try:
        from app.db import SessionLocal
        with SessionLocal() as db:
            record_event(db, kind, run_id=run_id, detail=detail)
    except Exception:
        pass


@dataclass
class TowerVitals:
    # Host
    heat_c: float | None
    heat_label: str
    heat_detail: str
    mem_used_mb: int
    mem_total_mb: int
    mem_pct: float
    load1: float
    cpu_label: str
    # Filter / search pulse
    last_ollama_at: datetime | None
    last_keyword_at: datetime | None
    last_browser_at: datetime | None
    searches_today: int
    searches_24h: int
    ollama_today: int
    ollama_24h: int
    keyword_today: int
    keyword_24h: int
    ollama_running: int
    # Capacity
    ollama_max_24h: int
    ollama_capacity_estimate: int
    capacity_note: str
    # Schedule
    next_search_at: datetime | None
    next_search_name: str
    next_search_secs: int | None
    scrape_running: bool
    scrape_running_name: str
    filter_mode_policy: str


def _mem() -> tuple[int, int, float]:
    total = used = 0
    try:
        text = Path('/proc/meminfo').read_text()
        vals = {}
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                vals[parts[0].rstrip(':')] = int(parts[1])
        total = vals.get('MemTotal', 0) // 1024
        avail = vals.get('MemAvailable', 0) // 1024
        used = max(0, total - avail)
    except Exception:
        pass
    pct = (100.0 * used / total) if total else 0.0
    return used, total, pct


def _cpu_label(load1: float, heat_level: str) -> str:
    cores = 1
    try:
        cores = max(1, int(Path('/proc/cpuinfo').read_text().count('processor')))
    except Exception:
        pass
    ratio = load1 / cores
    if heat_level == 'critical' or ratio >= 1.2:
        return 'Stressed'
    if heat_level == 'hot' or ratio >= 0.85:
        return 'Busy'
    if heat_level == 'warm' or ratio >= 0.5:
        return 'Working'
    return 'Healthy'


def _last_event(db: Session, kind: str) -> datetime | None:
    row = db.execute(
        select(TowerEvent.ts).where(TowerEvent.kind == kind)
        .order_by(desc(TowerEvent.ts)).limit(1)
    ).scalar_one_or_none()
    return row


def _count_events(db: Session, kind: str, since: datetime) -> int:
    return db.execute(
        select(func.count(TowerEvent.id)).where(
            TowerEvent.kind == kind, TowerEvent.ts >= since,
        )
    ).scalar() or 0


def _count_runs(db: Session, since: datetime) -> int:
    return db.execute(
        select(func.count(ScrapeRun.id)).where(
            ScrapeRun.started_at.is_not(None),
            ScrapeRun.started_at >= since,
        )
    ).scalar() or 0


def _next_search(db: Session, now: datetime) -> tuple[datetime | None, str]:
    from croniter import croniter
    best_when = None
    best_name = '—'
    for cfg in db.execute(
        select(SearchConfig).where(SearchConfig.enabled.is_(True))
    ).scalars():
        try:
            base = cfg.last_run_at or cfg.created_at or now
            if base.tzinfo is None:
                base = base.replace(tzinfo=timezone.utc)
            when = croniter(cfg.schedule_cron, base).get_next(datetime)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if best_when is None or when < best_when:
                best_when = when
                best_name = cfg.name
        except Exception:
            continue
    return best_when, best_name


def _capacity_estimate(db: Session, ollama_24h: int) -> tuple[int, str]:
    """Estimate sustainable Ollama-filtered searches / day on this laptop."""
    # Use avg duration of successful runs in last 24h that had ollama events
    since = utcnow() - timedelta(hours=24)
    runs = db.execute(
        select(ScrapeRun).where(
            ScrapeRun.status == 'success',
            ScrapeRun.started_at.is_not(None),
            ScrapeRun.finished_at.is_not(None),
            ScrapeRun.finished_at >= since,
        ).order_by(desc(ScrapeRun.id)).limit(40)
    ).scalars().all()
    durations = []
    for r in runs:
        try:
            secs = (r.finished_at - r.started_at).total_seconds()
            # Ignore aborted blips — real searches include ~75–105s dwell/page
            if secs >= 300:
                durations.append(secs)
        except Exception:
            continue
    if durations:
        avg = sum(durations) / len(durations)
        # One worker; add thermal breathing room (~25%)
        per_day = int((86400 / max(avg, 480)) * 0.75)
        # Cap early optimism: human stealth + Ollama rarely exceeds ~120/day
        per_day = max(24, min(per_day, 120))
        note = (
            f'Based on ~{avg / 60:.0f} min/search average with heat breaks; '
            f'one browser at a time. Target band for this ThinkPad: '
            f'{max(40, per_day - 15)}–{per_day + 10} Ollama searches/day before scaling laptops.'
        )
        return per_day, note
    # Prior: ~14 min stagger × human dwell → with Ollama GPU ~60–90
    return 72, (
        'Early estimate (not enough finished runs yet): ~60–90 Ollama searches/day '
        'on this P16 with headless Chrome + GPU filter + heat breaks. '
        'We will refine as the first-pass catalogue completes.'
    )


def compute_vitals(db: Session) -> TowerVitals:
    now = utcnow()
    # Local calendar day for "today"
    local = datetime.now().astimezone()
    local_midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start = local_midnight.astimezone(timezone.utc)
    since_24h = now - timedelta(hours=24)

    snap = thermal.snapshot()
    mem_used, mem_total, mem_pct = _mem()

    running = db.execute(
        select(ScrapeRun).where(ScrapeRun.status.in_(('running', 'dispatched')))
        .order_by(desc(ScrapeRun.id)).limit(1)
    ).scalar_one_or_none()
    running_name = '—'
    if running:
        cfg = db.get(SearchConfig, running.search_config_id)
        running_name = cfg.name if cfg else f'Run #{running.id}'

    ollama_running = 0
    if running:
        # If a run is active and last filter event for it was ollama (or none yet = assuming ollama policy)
        last = db.execute(
            select(TowerEvent).where(
                TowerEvent.run_id == running.id,
                TowerEvent.kind.in_(('ollama_filter', 'keyword_filter')),
            ).order_by(desc(TowerEvent.id)).limit(1)
        ).scalar_one_or_none()
        if last is None or last.kind == 'ollama_filter':
            ollama_running = 1

    next_at, next_name = _next_search(db, now)
    next_secs = None
    if next_at is not None:
        next_secs = max(0, int((next_at - now).total_seconds()))

    ollama_24h = _count_events(db, 'ollama_filter', since_24h)
    ollama_today = _count_events(db, 'ollama_filter', day_start)
    # Peak concurrent is 1 today; "max in 24h" = count of ollama-filtered searches
    # Also track high-water via events of kind ollama_filter
    capacity, capacity_note = _capacity_estimate(db, ollama_24h)

    return TowerVitals(
        heat_c=snap.cpu_c if snap.cpu_c is not None else snap.gpu_c,
        heat_label=snap.level.title(),
        heat_detail=snap.detail,
        mem_used_mb=mem_used,
        mem_total_mb=mem_total,
        mem_pct=mem_pct,
        load1=snap.load1,
        cpu_label=_cpu_label(snap.load1, snap.level),
        last_ollama_at=_last_event(db, 'ollama_filter'),
        last_keyword_at=_last_event(db, 'keyword_filter'),
        last_browser_at=_last_event(db, 'browser_open'),
        searches_today=_count_runs(db, day_start),
        searches_24h=_count_runs(db, since_24h),
        ollama_today=ollama_today,
        ollama_24h=ollama_24h,
        keyword_today=_count_events(db, 'keyword_filter', day_start),
        keyword_24h=_count_events(db, 'keyword_filter', since_24h),
        ollama_running=ollama_running,
        ollama_max_24h=ollama_24h,  # sequential worker → max handled = completed count
        ollama_capacity_estimate=capacity,
        capacity_note=capacity_note,
        next_search_at=next_at,
        next_search_name=next_name,
        next_search_secs=next_secs,
        scrape_running=running is not None,
        scrape_running_name=running_name,
        filter_mode_policy=config.RELEVANCE_MODE,
    )


def vitals_dict(db: Session) -> dict:
    v = compute_vitals(db)
    d = asdict(v)
    for key in ('last_ollama_at', 'last_keyword_at', 'last_browser_at', 'next_search_at'):
        val = d.get(key)
        d[key] = val.isoformat() if isinstance(val, datetime) else None
    d['vitals'] = v
    return d
