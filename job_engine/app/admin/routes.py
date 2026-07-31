from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Company, ConsoleLog, JobMaster, RequestLog, ScrapeRun, SearchConfig, TowerEvent
from app.schedule import FREQ_OPTIONS, WEEKDAYS, build_cron, cron_to_human
from app.signals import (
    WINDOW_OPTIONS,
    company_directory,
    compute_hiring_signals,
    format_delta,
    format_pct,
    set_watched,
    watchlist_rows,
)
from app.tasks import _config_busy, run_scrape
from app.tower_health import compute_vitals

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / 'templates'))


def _rel(value) -> Markup:
    """Render a datetime/date as a self-updating relative time element."""
    if not value:
        return Markup('<span class="muted">—</span>')
    iso = value.isoformat()
    return Markup(f'<time class="rel" datetime="{escape(iso)}">{escape(iso)}</time>')


def _fmt_countdown(secs: int | None) -> str:
    if secs is None:
        return '—'
    if secs <= 0:
        return 'due now'
    if secs < 60:
        return f'{secs}s'
    if secs < 3600:
        return f'{secs // 60}m {secs % 60}s'
    h, rem = divmod(secs, 3600)
    return f'{h}h {rem // 60}m'


templates.env.filters['rel'] = _rel
templates.env.filters['cron_human'] = cron_to_human
templates.env.filters['delta'] = format_delta
templates.env.filters['pct'] = format_pct
templates.env.filters['countdown'] = _fmt_countdown


def _page(request: Request, name: str, ctx: dict, db: Session):
    """Every admin page gets Tower Health vitals for the sticky header."""
    vitals = compute_vitals(db)
    payload = {'vitals': vitals, **ctx}
    return templates.TemplateResponse(request, name, payload)


def _vitals_json(v) -> dict:
    def iso(dt):
        return dt.isoformat() if dt is not None else None

    return {
        'heat_c': v.heat_c,
        'heat_label': v.heat_label,
        'heat_detail': v.heat_detail,
        'mem_used_mb': v.mem_used_mb,
        'mem_total_mb': v.mem_total_mb,
        'mem_pct': round(v.mem_pct, 1),
        'load1': round(v.load1, 2),
        'cpu_label': v.cpu_label,
        'last_ollama_at': iso(v.last_ollama_at),
        'last_keyword_at': iso(v.last_keyword_at),
        'last_browser_at': iso(v.last_browser_at),
        'searches_today': v.searches_today,
        'searches_24h': v.searches_24h,
        'ollama_today': v.ollama_today,
        'ollama_24h': v.ollama_24h,
        'keyword_today': v.keyword_today,
        'keyword_24h': v.keyword_24h,
        'ollama_running': v.ollama_running,
        'ollama_max_24h': v.ollama_max_24h,
        'ollama_capacity_estimate': v.ollama_capacity_estimate,
        'capacity_note': v.capacity_note,
        'next_search_at': iso(v.next_search_at),
        'next_search_name': v.next_search_name,
        'next_search_secs': v.next_search_secs,
        'next_search_label': _fmt_countdown(v.next_search_secs),
        'scrape_running': v.scrape_running,
        'scrape_running_name': v.scrape_running_name,
        'filter_mode_policy': v.filter_mode_policy,
    }


@router.get('/api/tower-vitals')
def api_tower_vitals(db: Session = Depends(get_db)):
    return JSONResponse(_vitals_json(compute_vitals(db)))


@router.get('/tower-health')
def tower_health(request: Request, db: Session = Depends(get_db)):
    vitals = compute_vitals(db)
    recent = db.execute(
        select(TowerEvent).order_by(desc(TowerEvent.id)).limit(40)
    ).scalars().all()
    return _page(request, 'tower_health.html', {
        'active': 'tower_health',
        'refresh': 3,
        'detail': vitals,
        'recent_events': recent,
        'event_labels': {
            'ollama_filter': 'Smart filter (Ollama)',
            'keyword_filter': 'Plan B keyword',
            'browser_open': 'Browser opened',
            'scrape_done': 'Search finished',
        },
    }, db)


@router.get('/')
def dashboard(request: Request, db: Session = Depends(get_db)):
    today = datetime.now(timezone.utc).date()
    stats = {
        'total_jobs': db.execute(select(func.count(JobMaster.id))).scalar(),
        'jobs_today': db.execute(
            select(func.count(JobMaster.id)).where(func.date(JobMaster.scraped_at) == today)
        ).scalar(),
        'companies': db.execute(select(func.count(Company.id))).scalar(),
        'configs_enabled': db.execute(
            select(func.count(SearchConfig.id)).where(SearchConfig.enabled.is_(True))
        ).scalar(),
        'runs_active': db.execute(
            select(func.count(ScrapeRun.id)).where(
                ScrapeRun.status.in_(('queued', 'dispatched', 'running'))
            )
        ).scalar(),
    }
    recent_runs = db.execute(
        select(ScrapeRun).order_by(desc(ScrapeRun.id)).limit(10)
    ).scalars().all()
    configs = {c.id: c for c in db.execute(select(SearchConfig)).scalars().all()}

    # Insights: who is hiring, for which roles, and how the week looked
    from datetime import timedelta
    week_ago = today - timedelta(days=7)
    top_companies = db.execute(
        select(Company.name, func.count(JobMaster.id).label('n'))
        .join(JobMaster, JobMaster.company_id == Company.id)
        .where(JobMaster.posted_date >= week_ago)
        .group_by(Company.name).order_by(desc('n')).limit(8)
    ).all()
    per_role = db.execute(
        select(SearchConfig.name, func.count(JobMaster.id).label('n'))
        .join(JobMaster, JobMaster.search_config_id == SearchConfig.id)
        .group_by(SearchConfig.name).order_by(desc('n'))
    ).all()
    daily = dict(db.execute(
        select(JobMaster.posted_date, func.count(JobMaster.id))
        .where(JobMaster.posted_date >= today - timedelta(days=13))
        .group_by(JobMaster.posted_date)
    ).all())
    daily_series = [
        {'day': (today - timedelta(days=13 - i)), 'n': daily.get(today - timedelta(days=13 - i), 0)}
        for i in range(14)
    ]
    latest_jobs = db.execute(
        select(JobMaster, Company.name)
        .outerjoin(Company, JobMaster.company_id == Company.id)
        .order_by(desc(JobMaster.scraped_at)).limit(6)
    ).all()

    signals = compute_hiring_signals(db, window_days=7)
    watched = watchlist_rows(db, window_days=7)[:6]

    return _page(request, 'dashboard.html', {
        'stats': stats, 'recent_runs': recent_runs, 'configs': configs,
        'top_companies': top_companies, 'per_role': per_role,
        'daily_series': daily_series, 'daily_max': max([d['n'] for d in daily_series] + [1]),
        'top_company_max': max([n for _, n in top_companies] + [1]),
        'per_role_max': max([n for _, n in per_role] + [1]),
        'latest_jobs': latest_jobs,
        'signals': signals,
        'watched': watched,
        'active': 'dashboard', 'refresh': 5,
    }, db)


@router.get('/signals')
def signals_page(request: Request, days: int = 7, db: Session = Depends(get_db)):
    if days not in (7, 14, 30):
        days = 7
    signals = compute_hiring_signals(db, window_days=days)
    return _page(request, 'signals.html', {
        'signals': signals,
        'window_options': WINDOW_OPTIONS,
        'active': 'signals',
        'refresh': 8,
    }, db)


@router.get('/watchlist')
def watchlist_page(
    request: Request,
    days: int = 7,
    q: str = '',
    add: str = '',
    db: Session = Depends(get_db),
):
    if days not in (7, 14, 30):
        days = 7
    watched = watchlist_rows(db, window_days=days, q=q)
    directory = company_directory(db, q=add or q, limit=50)
    return _page(request, 'watchlist.html', {
        'watched': watched,
        'directory': directory,
        'window_options': WINDOW_OPTIONS,
        'days': days,
        'f_q': q,
        'f_add': add,
        'active': 'watchlist',
        'refresh': 8,
    }, db)


@router.post('/watchlist/{company_id}/toggle')
def watchlist_toggle(
    company_id: int,
    next: str = Form('/watchlist'),
    db: Session = Depends(get_db),
):
    company = db.get(Company, company_id)
    if company is not None:
        set_watched(db, company_id, not bool(company.watched))
    # Only allow relative redirects inside the admin app
    if not next.startswith('/'):
        next = '/watchlist'
    return RedirectResponse(next, status_code=303)


@router.get('/configs')
def configs_page(request: Request, db: Session = Depends(get_db)):
    configs = db.execute(select(SearchConfig).order_by(SearchConfig.id)).scalars().all()
    return _page(request, 'configs.html', {
        'configs': configs, 'active': 'configs',
        'freq_options': FREQ_OPTIONS, 'weekdays': WEEKDAYS,
    }, db)


@router.post('/configs/create')
def create_config(
    name: str = Form(...),
    keywords: str = Form(...),
    geo_id: str = Form('102713980'),
    location_label: str = Form(''),
    schedule_freq: str = Form('daily'),
    schedule_time: str = Form(''),
    schedule_day: str = Form('Monday'),
    max_pages: int = Form(10),
    db: Session = Depends(get_db),
):
    db.add(SearchConfig(
        name=name.strip(),
        keywords=keywords.strip(),
        geo_id=geo_id.strip() or '102713980',
        location_label=location_label.strip() or None,
        schedule_cron=build_cron(schedule_freq, schedule_time, schedule_day),
        max_pages=max(1, min(max_pages, 40)),
    ))
    db.commit()
    return RedirectResponse('/configs', status_code=303)


@router.post('/configs/{config_id}/schedule')
def change_schedule(
    config_id: int,
    schedule_freq: str = Form('h1'),
    schedule_time: str = Form(''),
    schedule_day: str = Form('Monday'),
    db: Session = Depends(get_db),
):
    cfg = db.get(SearchConfig, config_id)
    if cfg:
        cfg.schedule_cron = build_cron(schedule_freq, schedule_time, schedule_day)
        db.commit()
    return RedirectResponse('/configs', status_code=303)


@router.post('/configs/{config_id}/toggle')
def toggle_config(config_id: int, db: Session = Depends(get_db)):
    cfg = db.get(SearchConfig, config_id)
    if cfg:
        cfg.enabled = not cfg.enabled
        db.commit()
    return RedirectResponse('/configs', status_code=303)


@router.post('/configs/{config_id}/run')
def run_config(
    config_id: int,
    scheduled_for: str = Form(''),
    db: Session = Depends(get_db),
):
    cfg = db.get(SearchConfig, config_id)
    if cfg is None:
        return RedirectResponse('/configs', status_code=303)

    now = datetime.now(timezone.utc)
    when = None
    if scheduled_for.strip():
        try:
            when = datetime.fromisoformat(scheduled_for).replace(tzinfo=timezone.utc)
        except ValueError:
            when = None

    immediate = when is None or when <= now
    if immediate and _config_busy(db, cfg.id):
        return RedirectResponse('/runs?busy=1', status_code=303)

    run = ScrapeRun(
        search_config_id=cfg.id,
        run_type='one_off',
        scheduled_for=when,
        target_date=(when or now).date(),
        status='dispatched' if immediate else 'queued',
    )
    db.add(run)
    db.commit()
    if immediate:
        run_scrape.delay(run.id)
    return RedirectResponse('/runs', status_code=303)


@router.get('/runs')
def runs_page(request: Request, db: Session = Depends(get_db)):
    runs = db.execute(select(ScrapeRun).order_by(desc(ScrapeRun.id)).limit(50)).scalars().all()
    configs = {c.id: c for c in db.execute(select(SearchConfig)).scalars().all()}
    logs = db.execute(
        select(RequestLog).order_by(desc(RequestLog.id)).limit(30)
    ).scalars().all()
    return _page(request, 'runs.html', {
        'runs': runs, 'configs': configs, 'logs': logs, 'active': 'runs',
        'refresh': 5,
    }, db)


@router.post('/runs/{run_id}/cancel')
def cancel_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(ScrapeRun, run_id)
    if run:
        if run.status in ('queued', 'dispatched'):
            run.status = 'cancelled'
            db.commit()
        elif run.status == 'running':
            # Worker checks this flag before each page and stops gracefully
            run.status = 'cancel_requested'
            db.commit()
    return RedirectResponse('/runs', status_code=303)


@router.post('/reset')
def reset_data(db: Session = Depends(get_db)):
    """Danger zone: wipe all runs, jobs, companies, request logs.

    Search configs are kept (their last_run_at is cleared). Blocked while
    a run is in progress — stop it first.
    """
    active = db.execute(
        select(ScrapeRun.id).where(
            ScrapeRun.status.in_(('running', 'cancel_requested'))
        ).limit(1)
    ).scalar_one_or_none()
    if active is not None:
        return RedirectResponse('/?reset_blocked=1', status_code=303)

    db.query(RequestLog).delete()
    db.query(JobMaster).delete()
    db.query(ScrapeRun).delete()
    db.query(Company).delete()
    for cfg in db.execute(select(SearchConfig)).scalars():
        cfg.last_run_at = None
    db.commit()

    # Drop any queued Celery messages so old runs don't resurrect
    try:
        from app.celery_app import celery as celery_app
        celery_app.control.purge()
    except Exception:
        pass

    return RedirectResponse('/?reset_done=1', status_code=303)


JOB_SORT_COLUMNS = {
    'title': lambda: JobMaster.title,
    'company': lambda: Company.name,
    'location': lambda: JobMaster.location,
    'posted': lambda: JobMaster.posted_date,
    'caught': lambda: JobMaster.scraped_at,
}


@router.get('/jobs')
def jobs_page(
    request: Request,
    q: str = '',
    company: str = '',
    posted: str = '',
    config_id: int = 0,
    sort: str = 'posted',
    dir: str = 'desc',
    db: Session = Depends(get_db),
):
    from datetime import date, timedelta

    filters = []
    if q.strip():
        filters.append(JobMaster.title.ilike(f'%{q.strip()}%'))
    if company.strip():
        filters.append(Company.name.ilike(f'%{company.strip()}%'))
    today = date.today()
    if posted == 'today':
        filters.append(JobMaster.posted_date == today)
    elif posted == 'yesterday':
        filters.append(JobMaster.posted_date == today - timedelta(days=1))
    elif posted == 'week':
        filters.append(JobMaster.posted_date >= today - timedelta(days=7))
    if config_id:
        filters.append(JobMaster.search_config_id == config_id)

    if sort not in JOB_SORT_COLUMNS:
        sort = 'posted'
    dir = 'asc' if dir == 'asc' else 'desc'
    col = JOB_SORT_COLUMNS[sort]()
    order = col.asc().nullslast() if dir == 'asc' else col.desc().nullslast()

    query = (
        select(JobMaster, Company.name)
        .outerjoin(Company, JobMaster.company_id == Company.id)
        .where(*filters)
        .order_by(order, desc(JobMaster.scraped_at))
        .limit(200)
    )
    total = db.execute(
        select(func.count(JobMaster.id))
        .outerjoin(Company, JobMaster.company_id == Company.id)
        .where(*filters)
    ).scalar()

    rows = db.execute(query).all()
    all_configs = db.execute(select(SearchConfig).order_by(SearchConfig.name)).scalars().all()
    company_names = db.execute(
        select(Company.name).order_by(Company.name).limit(300)
    ).scalars().all()
    return _page(request, 'jobs.html', {
        'rows': rows, 'total': total, 'active': 'jobs',
        'all_configs': all_configs, 'company_names': company_names,
        'f_q': q, 'f_company': company, 'f_posted': posted, 'f_config': config_id,
        'f_sort': sort, 'f_dir': dir,
    }, db)


@router.post('/console/clear')
def console_clear(db: Session = Depends(get_db)):
    cleared = db.query(ConsoleLog).delete()
    db.commit()
    return {'cleared': cleared}


@router.get('/console')
def console_page(request: Request, db: Session = Depends(get_db)):
    entries = db.execute(
        select(ConsoleLog).order_by(desc(ConsoleLog.id)).limit(300)
    ).scalars().all()
    entries.reverse()

    # Collapse consecutive AI "think" rows of the same run into one entry and
    # annotate each line with the seconds elapsed since that run's previous line.
    display = []
    prev_ts: dict = {}
    for e in entries:
        text = e.message
        if text.startswith('thinking: '):
            text = text[len('thinking: '):]
        is_think = (e.source == 'ai' and (e.level == 'think' or e.message.startswith('thinking: ')))
        if is_think and display and display[-1]['think'] and display[-1]['run_id'] == e.run_id:
            display[-1]['full'] += ' ' + text
            display[-1]['ts'] = e.ts
            continue
        delta = ''
        key = e.run_id or 0
        if key in prev_ts:
            secs = (e.ts - prev_ts[key]).total_seconds()
            if secs >= 1:
                delta = f'+{int(secs)}s'
        prev_ts[key] = e.ts
        display.append({
            'id': e.id, 'ts': e.ts, 'source': e.source, 'level': e.level,
            'run_id': e.run_id, 'full': text, 'think': is_think, 'delta': delta,
        })

    running = db.execute(
        select(ScrapeRun).where(ScrapeRun.status.in_(('running', 'cancel_requested')))
    ).scalars().all()
    configs = {c.id: c for c in db.execute(select(SearchConfig)).scalars().all()}

    # Latest non-think message per running run = its current phase
    phases = {}
    for run in running:
        last = db.execute(
            select(ConsoleLog).where(ConsoleLog.run_id == run.id, ConsoleLog.level != 'think')
            .order_by(desc(ConsoleLog.id)).limit(1)
        ).scalar_one_or_none()
        phases[run.id] = last.message[:90] if last else '—'

    return _page(request, 'console.html', {
        'display': display, 'running': running, 'configs': configs, 'phases': phases,
        'active': 'console',
        'last_id': entries[-1].id if entries else 0,
    }, db)
