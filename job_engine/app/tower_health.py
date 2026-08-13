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
from app.models import JobMaster, ScrapeRun, SearchConfig, TowerEvent


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
    # Alert traffic light + browser mode
    alert_level: str  # ok | planb | blocked
    alert_label: str
    headless: bool
    block: dict | None
    planb_detail: str
    planb_at: str | None
    next_search_label: str
    backlog_waiting: int
    ollama_live: bool
    phase_label: str
    last_ollama_label: str
    # Big live countdown clock
    countdown_mode: str  # searching | to_start | paused | idle
    countdown_secs: int
    countdown_title: str
    countdown_role: str
    scrape_started_at: datetime | None
    avg_search_secs: int
    # Detail enrich (Plan B, discovery-first)
    detail_mode: str  # off | light | full
    detail_used_today: int
    detail_budget_per_day: int
    detail_pending: int
    # Engine stall — the tower must never say "healthy" while collection is dead
    stalled: bool
    stall_detail: str


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


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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


def _schedule_snapshot(db: Session, now: datetime) -> dict:
    """Next role + backlog. Never leave Ashok with a vague past 'due now'."""
    from croniter import croniter

    overdue: list[tuple[datetime, int, str]] = []
    future: list[tuple[datetime, str]] = []
    for cfg in db.execute(
        select(SearchConfig).where(SearchConfig.enabled.is_(True))
        .order_by(SearchConfig.priority.asc(), SearchConfig.id.asc())
    ).scalars():
        try:
            base = _aware(cfg.last_run_at or cfg.created_at or now)
            when = _aware(croniter(cfg.schedule_cron, base).get_next(datetime))
            if when <= now:
                overdue.append((when, cfg.priority, cfg.name))
            else:
                future.append((when, cfg.name))
        except Exception:
            continue

    overdue.sort(key=lambda row: (row[0], row[1], row[2]))
    future.sort(key=lambda row: row[0])

    if overdue:
        return {
            'when': now,
            'name': overdue[0][2],
            'secs': 0,
            'backlog': len(overdue),
            'mode': 'backlog',
        }
    if future:
        when, name = future[0]
        return {
            'when': when,
            'name': name,
            'secs': max(0, int((when - now).total_seconds())),
            'backlog': 0,
            'mode': 'scheduled',
        }
    return {'when': None, 'name': '—', 'secs': None, 'backlog': 0, 'mode': 'idle'}


def _phase_from_console(db: Session, run_id: int | None) -> str:
    if not run_id:
        return ''
    from app.models import ConsoleLog
    last = db.execute(
        select(ConsoleLog).where(ConsoleLog.run_id == run_id)
        .order_by(desc(ConsoleLog.id)).limit(1)
    ).scalar_one_or_none()
    if not last:
        return ''
    msg = (last.message or '').lower()
    if any(k in msg for k in ('batch', 'checking', 'ollama', 'heat break', 'relevance')):
        return 'filtering'
    if any(k in msg for k in ('navigat', 'browsing', 'scrolling', 'page ', 'dwell', 'cards')):
        return 'browsing'
    if any(k in msg for k in ('opening browser', 'syncing')):
        return 'opening'
    return 'working'


def _fmt_next_label(*, scrape_running: bool, running_name: str, phase: str,
                    heat_level: str, allow_new: bool, sched: dict) -> str:
    if scrape_running:
        phase_word = {
            'filtering': 'Filtering with Ollama',
            'browsing': 'Browsing LinkedIn',
            'opening': 'Opening browser',
        }.get(phase, 'In progress')
        short = running_name if len(running_name) <= 28 else running_name[:25] + '…'
        backlog = sched.get('backlog') or 0
        # Current role is already running — waiting = others still overdue
        waiting_others = max(0, backlog - 1) if backlog else 0
        if waiting_others:
            return f'{phase_word} · {short} · then {waiting_others} waiting'
        return f'{phase_word} · {short}'

    if not allow_new and heat_level in ('hot', 'critical'):
        name = sched.get('name') or '—'
        n = sched.get('backlog') or 0
        extra = f' · {n} waiting' if n else ''
        return f'Paused (PC heat) · next {name}{extra}'

    if sched.get('mode') == 'backlog':
        n = sched.get('backlog') or 0
        name = sched.get('name') or '—'
        return f'Starting next · {name} · {n} waiting'

    if sched.get('mode') == 'scheduled' and sched.get('secs') is not None:
        secs = int(sched['secs'])
        name = sched.get('name') or '—'
        if secs < 60:
            return f'In {secs}s · {name}'
        if secs < 3600:
            return f'In {secs // 60}m · {name}'
        h, rem = divmod(secs, 3600)
        return f'In {h}h {rem // 60}m · {name}'

    return 'No searches queued'


def _last_ollama_pulse(db: Session, now: datetime) -> tuple[datetime | None, bool, str]:
    """(timestamp, live_now, label). Live AI logs beat stale finished events."""
    from app.models import ConsoleLog

    recent = db.execute(
        select(ConsoleLog).where(
            ConsoleLog.source == 'ai',
            ConsoleLog.ts >= now - timedelta(minutes=3),
        ).order_by(desc(ConsoleLog.id)).limit(1)
    ).scalar_one_or_none()
    if recent is not None:
        return _aware(recent.ts), True, 'filtering now'

    ts = db.execute(
        select(TowerEvent.ts).where(
            TowerEvent.kind.in_(('ollama_filter', 'ollama_batch'))
        ).order_by(desc(TowerEvent.ts)).limit(1)
    ).scalar_one_or_none()
    if ts is None:
        return None, False, 'never'
    return _aware(ts), False, ''


def _next_search(db: Session, now: datetime) -> tuple[datetime | None, str]:
    """Compat wrapper — prefer _schedule_snapshot for UI."""
    snap = _schedule_snapshot(db, now)
    return snap.get('when'), snap.get('name') or '—'


def _avg_search_secs(db: Session) -> int:
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
            if secs >= 300:
                durations.append(secs)
        except Exception:
            continue
    if durations:
        return int(sum(durations) / len(durations))
    return 720  # ~12 min default with dwell + Ollama


def _countdown_clock(
    *,
    running: ScrapeRun | None,
    running_name: str,
    sched: dict,
    allow_new: bool,
    heat_level: str,
    avg_secs: int,
    now: datetime,
) -> tuple[str, int, str, str, datetime | None]:
    """mode, secs, title, role, scrape_started_at — for the square live card."""
    if running is not None and running.started_at is not None:
        started = _aware(running.started_at)
        elapsed = max(0, int((now - started).total_seconds()))
        remaining = max(20, avg_secs - elapsed)
        short = running_name if len(running_name) <= 36 else running_name[:33] + '…'
        return 'searching', remaining, f'Searching {short}', short, started

    name = sched.get('name') or '—'
    short = name if len(name) <= 36 else name[:33] + '…'

    if not allow_new and heat_level in ('hot', 'critical'):
        return 'paused', 0, f'Paused (heat) · next {short}', short, None

    if sched.get('mode') == 'backlog':
        wait = int(getattr(config, 'BEAT_SCAN_INTERVAL_S', 90) or 90)
        return 'to_start', wait, f'Next · {short}', short, None

    if sched.get('mode') == 'scheduled' and sched.get('secs') is not None:
        return 'to_start', int(sched['secs']), f'Next · {short}', short, None

    return 'idle', 0, 'Tower idle', '—', None


def _age_label(delta: timedelta) -> str:
    secs = max(0, int(delta.total_seconds()))
    if secs < 3600:
        return f'{secs // 60}m'
    hours = secs // 3600
    if hours < 48:
        return f'{hours}h'
    return f'{hours // 24}d {hours % 24}h'


def _detect_stall(
    *,
    running_started_at: datetime | None,
    running_name: str,
    newest_started_at: datetime | None,
    backlog: int,
    allow_new: bool,
    now: datetime,
) -> tuple[bool, str]:
    """Is the collection engine (Celery worker + beat) actually alive?

    A healthy beat tick reaps any run stuck in running/dispatched within
    STALE_RUN_MINUTES — so a run "running" far past that means no tick has
    happened. Likewise an overdue backlog nobody dispatches for a long time
    while the host is cool means beat is down. Without this check the header
    said "Tower healthy" through a full engine outage (2026-08-13 incident:
    a Junior Software Developer run sat "running" 24h+ with all counters 0).
    """
    reap_grace = timedelta(minutes=config.STALE_RUN_MINUTES + 15)
    if running_started_at is not None:
        age = now - _aware(running_started_at)
        if age > reap_grace:
            return True, (
                f'"{running_name}" has shown as running for {_age_label(age)} '
                f'— the engine should finish or reap it within '
                f'{config.STALE_RUN_MINUTES} min. Worker/beat looks down; '
                f'restart the tower stack on the ThinkPad.'
            )
        return False, ''

    if backlog and allow_new and newest_started_at is not None:
        idle = now - _aware(newest_started_at)
        if idle > timedelta(minutes=30):
            plural = 'es' if backlog != 1 else ''
            return True, (
                f'{backlog} search{plural} overdue but nothing has started '
                f'for {_age_label(idle)} — the scheduler (beat) is not '
                f'dispatching. Restart the tower stack on the ThinkPad.'
            )
    return False, ''


def _capacity_estimate(db: Session, ollama_24h: int) -> tuple[int, str]:
    """Estimate sustainable Ollama-filtered searches / day on this laptop."""
    avg = float(_avg_search_secs(db))
    if avg >= 300:
        per_day = int((86400 / max(avg, 480)) * 0.75)
        per_day = max(24, min(per_day, 120))
        note = (
            f'Based on ~{avg / 60:.0f} min/search average with heat breaks; '
            f'one browser at a time. Target band for this ThinkPad: '
            f'{max(40, per_day - 15)}–{per_day + 10} Ollama searches/day before scaling laptops.'
        )
        return per_day, note
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
    phase = _phase_from_console(db, running.id if running else None)
    if running and phase == 'filtering':
        ollama_running = 1
    elif running:
        last = db.execute(
            select(TowerEvent).where(
                TowerEvent.run_id == running.id,
                TowerEvent.kind.in_(('ollama_filter', 'ollama_batch', 'keyword_filter')),
            ).order_by(desc(TowerEvent.id)).limit(1)
        ).scalar_one_or_none()
        if last is None or last.kind != 'keyword_filter':
            ollama_running = 1

    sched = _schedule_snapshot(db, now)
    next_at = sched.get('when')
    next_name = sched.get('name') or '—'
    next_secs = sched.get('secs')

    ollama_24h = _count_events(db, 'ollama_filter', since_24h)
    ollama_today = _count_events(db, 'ollama_filter', day_start)
    capacity, capacity_note = _capacity_estimate(db, ollama_24h)

    keyword_24h = _count_events(db, 'keyword_filter', since_24h)
    last_kw = _last_event(db, 'keyword_filter')
    # Sticky Plan B banner only while Ollama is still blocked — clear as soon
    # as heat/GPU recover (do not keep orange for 30 minutes after recovery).
    planb_recent = False
    if last_kw is not None and not thermal.ollama_path_open():
        kw_ts = _aware(last_kw)
        planb_recent = (now - kw_ts).total_seconds() < 1800

    from app.runtime_settings import (
        get_detail_enrich_mode, get_headless, tower_alert_state,
    )
    alert = tower_alert_state(planb_recent=planb_recent)
    allow_new, _heat = thermal.allow_new_scrape()

    detail_mode = get_detail_enrich_mode()
    try:
        from app.detail_budget import used_today
        detail_used = used_today()
    except Exception:
        detail_used = 0
    detail_pending = db.execute(
        select(func.count(JobMaster.id)).where(
            JobMaster.requirements_enriched_at.is_(None)
        )
    ).scalar() or 0

    newest_started = db.execute(
        select(func.max(ScrapeRun.started_at)).where(
            ScrapeRun.started_at.is_not(None)
        )
    ).scalar()
    stalled, stall_detail = _detect_stall(
        running_started_at=running.started_at if running else None,
        running_name=running_name,
        newest_started_at=newest_started,
        backlog=int(sched.get('backlog') or 0),
        allow_new=allow_new,
        now=now,
    )
    if stalled and alert.get('level') != 'blocked':
        alert = dict(alert)
        alert['level'] = 'stalled'
        alert['label'] = 'Collection stalled — engine not running'

    ollama_at, ollama_live, ollama_lbl = _last_ollama_pulse(db, now)
    if ollama_live:
        phase = 'filtering'
    next_label = _fmt_next_label(
        scrape_running=running is not None,
        running_name=running_name,
        phase=phase,
        heat_level=snap.level,
        allow_new=allow_new,
        sched=sched,
    )
    avg_secs = _avg_search_secs(db)
    cd_mode, cd_secs, cd_title, cd_role, scrape_started = _countdown_clock(
        running=running,
        running_name=running_name,
        sched=sched,
        allow_new=allow_new,
        heat_level=snap.level,
        avg_secs=avg_secs,
        now=now,
    )
    if stalled:
        # Never keep claiming "Searching X" for a run the dead engine abandoned
        cd_mode, cd_secs = 'stalled', 0
        if running is not None:
            short = running_name if len(running_name) <= 36 else running_name[:33] + '…'
            cd_title = f'Stuck · {short} — engine down?'
            next_label = f'Stalled · {short}'
        else:
            cd_title = 'Stalled · engine not running'
            next_label = 'Stalled · engine not running'

    return TowerVitals(
        heat_c=snap.cpu_c if snap.cpu_c is not None else snap.gpu_c,
        heat_label=snap.level.title(),
        heat_detail=snap.detail,
        mem_used_mb=mem_used,
        mem_total_mb=mem_total,
        mem_pct=mem_pct,
        load1=snap.load1,
        cpu_label=_cpu_label(snap.load1, snap.level),
        last_ollama_at=ollama_at,
        last_keyword_at=last_kw,
        last_browser_at=_last_event(db, 'browser_open'),
        searches_today=_count_runs(db, day_start),
        searches_24h=_count_runs(db, since_24h),
        ollama_today=ollama_today,
        ollama_24h=ollama_24h,
        keyword_today=_count_events(db, 'keyword_filter', day_start),
        keyword_24h=keyword_24h,
        ollama_running=ollama_running,
        ollama_max_24h=ollama_24h,
        ollama_capacity_estimate=capacity,
        capacity_note=capacity_note,
        next_search_at=next_at,
        next_search_name=next_name,
        next_search_secs=next_secs,
        scrape_running=running is not None,
        scrape_running_name=running_name,
        filter_mode_policy=config.RELEVANCE_MODE,
        alert_level=alert['level'],
        alert_label=alert['label'],
        headless=get_headless(),
        block=alert.get('block'),
        planb_detail=alert.get('planb_detail') or '',
        planb_at=alert.get('planb_at'),
        next_search_label=next_label,
        backlog_waiting=int(sched.get('backlog') or 0),
        ollama_live=ollama_live,
        phase_label=phase,
        last_ollama_label=ollama_lbl,
        countdown_mode=cd_mode,
        countdown_secs=cd_secs,
        countdown_title=cd_title,
        countdown_role=cd_role,
        scrape_started_at=scrape_started,
        avg_search_secs=avg_secs,
        detail_mode=detail_mode,
        detail_used_today=detail_used,
        detail_budget_per_day=config.DETAIL_BUDGET_PER_DAY,
        detail_pending=int(detail_pending),
        stalled=stalled,
        stall_detail=stall_detail,
    )


def vitals_dict(db: Session) -> dict:
    v = compute_vitals(db)
    d = asdict(v)
    for key in ('last_ollama_at', 'last_keyword_at', 'last_browser_at', 'next_search_at',
                'scrape_started_at'):
        val = d.get(key)
        d[key] = val.isoformat() if isinstance(val, datetime) else None
    d['vitals'] = v
    return d
