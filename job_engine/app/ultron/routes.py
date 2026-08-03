"""Ultron routes: WebSocket bus + JSON payloads for VIGIL panels."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Company, JobMaster, ScrapeRun, SearchConfig, TowerEvent
from app.runtime_settings import get_headless, set_headless, dismiss_linkedin_block
from app.signals import (
    ALLOWED_WINDOWS,
    WINDOW_OPTIONS,
    _window_bounds,
    cities_for_role,
    companies_for_role,
    company_directory,
    compute_hiring_signals,
    set_watched,
    watchlist_rows,
)
from app.ai_capacity import compute_ai_capacity
from app.cities import city_options, normalize_city_filter
from app.city_analytics import compare_cities, compute_city_signals
from app.experience_bands import experience_clause, experience_options, normalize_experience
from app.filter_compare import ALLOWED_FILTER_WINDOWS, compute_filter_compare
from app.hermes_ask import ask_hermes
from app.role_analytics import roles_in_window
from app.sectors import CRITICAL_SECTORS, normalize_sector, sector_options
from app.tasks import _config_busy, run_scrape
from app.tower_health import compute_vitals
from app.ultron.hub import hub
from app.ultron.serialize import to_jsonable
from app.vigil_boards import BOARD_HELP, render_board, resolve_board
from app.world_model import compute_world_model
from app.city_skyline import compute_city_skyline, compute_jobs_skyline

router = APIRouter(tags=['ultron'])

VIGIL_DIST = Path(__file__).resolve().parents[2] / 'vigil' / 'dist'


def _iso(dt):
    return dt.isoformat() if dt is not None else None


def _vitals_json(v) -> dict:
    return {
        'heat_c': v.heat_c,
        'heat_label': v.heat_label,
        'heat_detail': v.heat_detail,
        'mem_used_mb': v.mem_used_mb,
        'mem_total_mb': v.mem_total_mb,
        'mem_pct': round(v.mem_pct, 1),
        'load1': round(v.load1, 2),
        'cpu_label': v.cpu_label,
        'last_ollama_at': _iso(v.last_ollama_at),
        'last_keyword_at': _iso(v.last_keyword_at),
        'last_browser_at': _iso(v.last_browser_at),
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
        'next_search_at': _iso(v.next_search_at),
        'next_search_name': v.next_search_name,
        'next_search_secs': v.next_search_secs,
        'next_search_label': v.next_search_label,
        'backlog_waiting': v.backlog_waiting,
        'scrape_running': v.scrape_running,
        'scrape_running_name': v.scrape_running_name,
        'filter_mode_policy': v.filter_mode_policy,
        'alert_level': v.alert_level,
        'alert_label': v.alert_label,
        'headless': v.headless,
        'block': v.block,
        'planb_detail': v.planb_detail,
        'planb_at': v.planb_at,
        'ollama_live': v.ollama_live,
        'phase_label': v.phase_label,
        'last_ollama_label': v.last_ollama_label,
        'countdown_mode': v.countdown_mode,
        'countdown_secs': v.countdown_secs,
        'countdown_title': v.countdown_title,
        'countdown_role': v.countdown_role,
        'scrape_started_at': _iso(v.scrape_started_at),
        'avg_search_secs': v.avg_search_secs,
    }


@router.websocket('/ws/ultron')
async def ws_ultron(ws: WebSocket):
    await hub.connect(ws)
    try:
        while True:
            raw = await ws.receive_json()
            if not isinstance(raw, dict):
                continue
            await hub.handle_message(ws, raw)
    except WebSocketDisconnect:
        await hub.disconnect(ws)
    except Exception:
        await hub.disconnect(ws)


@router.get('/api/ultron/status')
def ultron_status(db: Session = Depends(get_db)):
    return {
        'name': 'VIGIL',
        'backend': 'ultron',
        'status': hub.status_line,
        'clients': hub.client_count,
        'vitals': _vitals_json(compute_vitals(db)),
    }


@router.get('/api/ultron/world-model')
def ultron_world_model(days: int = 7, db: Session = Depends(get_db)):
    """Summarised labor-market graph for the Neural Core (live Postgres)."""
    payload = compute_world_model(db, window_days=days)
    payload['generated_at'] = _iso(datetime.now(timezone.utc))
    payload['window_options'] = [
        {'days': d, 'label': label} for d, label in WINDOW_OPTIONS
    ]
    return payload


@router.get('/api/ultron/tower')
def ultron_tower(
    sector: str | None = None, city: str | None = None,
    experience: str | None = None,
    db: Session = Depends(get_db),
):
    today = datetime.now(timezone.utc).date()
    week_ago = today - timedelta(days=7)
    sector = normalize_sector(sector)
    city = normalize_city_filter(city)
    experience = normalize_experience(experience)
    exp = experience_clause(experience)
    co_q = (
        select(Company.id, Company.name, func.count(JobMaster.id).label('n'))
        .join(JobMaster, JobMaster.company_id == Company.id)
        .where(JobMaster.posted_date >= week_ago)
        .group_by(Company.id, Company.name).order_by(desc('n')).limit(8)
    )
    if sector:
        co_q = co_q.where(JobMaster.sector == sector)
    if city:
        co_q = co_q.where(JobMaster.city_key == city)
    if exp is not None:
        co_q = co_q.where(exp)
    top_companies = db.execute(co_q).all()
    # Fair: same 7d window as top companies — early-started roles no longer dominate
    fair_roles = roles_in_window(
        db, days=7, limit=40, mode='count', sector=sector, city=city,
        experience=experience,
    )
    per_role = fair_roles['roles']
    daily_q = (
        select(JobMaster.posted_date, func.count(JobMaster.id))
        .where(JobMaster.posted_date >= today - timedelta(days=13))
        .group_by(JobMaster.posted_date)
    )
    if sector:
        daily_q = daily_q.where(JobMaster.sector == sector)
    if city:
        daily_q = daily_q.where(JobMaster.city_key == city)
    if exp is not None:
        daily_q = daily_q.where(exp)
    daily = dict(db.execute(daily_q).all())
    daily_series = [
        {'day': str(today - timedelta(days=13 - i)), 'n': daily.get(today - timedelta(days=13 - i), 0)}
        for i in range(14)
    ]
    latest_q = (
        select(JobMaster, Company.id, Company.name)
        .outerjoin(Company, JobMaster.company_id == Company.id)
        .order_by(desc(JobMaster.scraped_at)).limit(8)
    )
    if sector:
        latest_q = latest_q.where(JobMaster.sector == sector)
    if city:
        latest_q = latest_q.where(JobMaster.city_key == city)
    if exp is not None:
        latest_q = latest_q.where(exp)
    latest = db.execute(latest_q).all()
    signals = compute_hiring_signals(
        db, window_days=7, sector=sector, city=city, experience=experience,
    )
    watched = watchlist_rows(
        db, window_days=7, sector=sector, city=city, experience=experience,
    )[:6]
    city_teaser = compute_city_signals(
        db, window_days=7, sector=sector, experience=experience,
    )
    jobs_q = select(func.count(JobMaster.id))
    today_q = select(func.count(JobMaster.id)).where(func.date(JobMaster.scraped_at) == today)
    cfg_q = select(func.count(SearchConfig.id)).where(SearchConfig.enabled.is_(True))
    # Companies must respect city/sector/experience — never return all-India count for a city
    companies_q = select(func.count(func.distinct(JobMaster.company_id))).where(
        JobMaster.company_id.is_not(None)
    )
    if sector:
        jobs_q = jobs_q.where(JobMaster.sector == sector)
        today_q = today_q.where(JobMaster.sector == sector)
        cfg_q = cfg_q.where(SearchConfig.sector == sector)
        companies_q = companies_q.where(JobMaster.sector == sector)
    if city:
        jobs_q = jobs_q.where(JobMaster.city_key == city)
        today_q = today_q.where(JobMaster.city_key == city)
        companies_q = companies_q.where(JobMaster.city_key == city)
    if exp is not None:
        jobs_q = jobs_q.where(exp)
        today_q = today_q.where(exp)
        companies_q = companies_q.where(exp)
    return {
        'stats': {
            'total_jobs': db.execute(jobs_q).scalar(),
            'jobs_today': db.execute(today_q).scalar(),
            'companies': db.execute(companies_q).scalar(),
            'configs_enabled': db.execute(cfg_q).scalar(),
            'runs_active': db.execute(
                select(func.count(ScrapeRun.id)).where(
                    ScrapeRun.status.in_(('queued', 'dispatched', 'running'))
                )
            ).scalar(),
        },
        'top_companies': [
            {'company_id': cid, 'name': n, 'n': c} for cid, n, c in top_companies
        ],
        'per_role': per_role,
        'per_role_window_days': 7,
        'fair_hint': fair_roles.get('fair_hint'),
        'sector': sector or '',
        'city': city or '',
        'experience': experience or '',
        'sectors': CRITICAL_SECTORS,
        'sector_options': sector_options(),
        'city_options': city_options(),
        'experience_options': experience_options(),
        'top_cities': (city_teaser.get('cities') or [])[:6],
        'window_options': [{'days': d, 'label': label} for d, label in WINDOW_OPTIONS],
        'daily_series': daily_series,
        'latest_jobs': [{
            'id': j.id,
            'title': j.title,
            'company_id': cid,
            'company': cname,
            'location': j.location,
            'city_key': j.city_key,
            'experience_band': j.experience_band,
            'job_url': j.job_url,
            'scraped_at': _iso(j.scraped_at),
            'posted_date': str(j.posted_date) if j.posted_date else None,
        } for j, cid, cname in latest],
        'signals_teaser': to_jsonable(signals),
        'watched': to_jsonable(watched),
    }


@router.get('/api/ultron/jobs-skyline')
def ultron_jobs_skyline(
    sector: str | None = None,
    city: str | None = None,
    experience: str | None = None,
    limit: int = 120,
    db: Session = Depends(get_db),
):
    """Multi-city campus from Jobs filters — one building cluster per city."""
    return compute_jobs_skyline(
        db, sector=sector, city=city, experience=experience, limit=limit,
    )


@router.get('/api/ultron/cities/{city_id}/skyline')
def ultron_city_skyline(
    city_id: str, days: int = 7, limit: int = 28, db: Session = Depends(get_db),
):
    """Employers for night-city district — height = hiring, clustered by sector."""
    return compute_city_skyline(db, city=city_id, window_days=days, limit=limit)


@router.get('/api/ultron/top-companies')
def ultron_top_companies(
    days: int = 7, limit: int = 80, sector: str | None = None,
    city: str | None = None, experience: str | None = None,
    db: Session = Depends(get_db),
):
    """Full company hiring ranking for Show all — max → min."""
    if days not in ALLOWED_WINDOWS:
        days = 7
    sector = normalize_sector(sector)
    city = normalize_city_filter(city)
    experience = normalize_experience(experience)
    limit = max(1, min(limit, 200))
    _days, recent_start, recent_end, _ps, _pe, by_scraped = _window_bounds(days)
    time_col = JobMaster.scraped_at if by_scraped else JobMaster.posted_date
    q = (
        select(Company.id, Company.name, func.count(JobMaster.id).label('n'))
        .join(JobMaster, JobMaster.company_id == Company.id)
        .where(time_col >= recent_start, time_col < recent_end)
        .group_by(Company.id, Company.name)
        .order_by(desc('n'))
        .limit(limit)
    )
    if sector:
        q = q.where(JobMaster.sector == sector)
    if city:
        q = q.where(JobMaster.city_key == city)
    exp = experience_clause(experience)
    if exp is not None:
        q = q.where(exp)
    rows = db.execute(q).all()
    max_n = max([n for _, _, n in rows] + [1])
    return {
        'days': days,
        'sector': sector or '',
        'city': city or '',
        'experience': experience or '',
        'sector_options': sector_options(),
        'city_options': city_options(),
        'experience_options': experience_options(),
        'window_options': [{'days': d, 'label': label} for d, label in WINDOW_OPTIONS],
        'max': max_n,
        'total': len(rows),
        'companies': [
            {'company_id': cid, 'name': name, 'n': n} for cid, name, n in rows
        ],
    }


@router.get('/api/ultron/roles-rank')
def ultron_roles_rank(
    days: int = 7,
    mode: str = 'count',
    limit: int = 200,
    sector: str | None = None,
    city: str | None = None,
    experience: str | None = None,
    db: Session = Depends(get_db),
):
    """Jobs-per-role ranking — windowed (fair) count or per-day rate."""
    experience = normalize_experience(experience)
    data = roles_in_window(
        db, days=days, limit=limit, mode=mode, sector=sector, city=city,
        experience=experience,
    )
    data['sector'] = normalize_sector(sector) or ''
    data['city'] = normalize_city_filter(city) or ''
    data['experience'] = experience or ''
    data['sector_options'] = sector_options()
    data['city_options'] = city_options()
    data['experience_options'] = experience_options()
    return data


@router.get('/api/ultron/sectors')
def ultron_sectors():
    """Critical sector catalogue for UI filters and labels."""
    return {'sectors': CRITICAL_SECTORS, 'sector_options': sector_options()}


@router.get('/api/ultron/cities')
def ultron_cities(
    days: int = 7, sector: str | None = None,
    experience: str | None = None, db: Session = Depends(get_db),
):
    """City hiring signals — volume + growth ranking."""
    if days not in ALLOWED_WINDOWS:
        days = 7
    return to_jsonable(compute_city_signals(
        db, window_days=days, sector=sector, experience=experience,
    ))


@router.get('/api/ultron/cities/compare')
def ultron_cities_compare(
    a: str = '',
    b: str = '',
    days: int = 7,
    sector: str | None = None,
    experience: str | None = None,
    db: Session = Depends(get_db),
):
    """Side-by-side hiring snapshot for two cities."""
    if days not in ALLOWED_WINDOWS:
        days = 7
    return to_jsonable(compare_cities(
        db, a, b, window_days=days, sector=sector, experience=experience,
    ))


@router.get('/api/ultron/signals')
def ultron_signals(
    days: int = 7,
    sector: str | None = None,
    city: str | None = None,
    experience: str | None = None,
    db: Session = Depends(get_db),
):
    if days not in ALLOWED_WINDOWS:
        days = 7
    sector = normalize_sector(sector)
    city = normalize_city_filter(city)
    experience = normalize_experience(experience)
    return {
        'days': days,
        'sector': sector or '',
        'city': city or '',
        'experience': experience or '',
        'sector_options': sector_options(),
        'city_options': city_options(),
        'experience_options': experience_options(),
        'window_options': [{'days': d, 'label': label} for d, label in WINDOW_OPTIONS],
        'signals': to_jsonable(
            compute_hiring_signals(
                db, window_days=days, sector=sector, city=city,
                experience=experience,
            )
        ),
    }


@router.get('/api/ultron/filter-compare')
def ultron_filter_compare(window: str = '24h', db: Session = Depends(get_db)):
    """AI (Ollama) vs Keyword (Plan B) filter counts for a time window."""
    key = (window or '24h').strip().lower()
    if key not in ALLOWED_FILTER_WINDOWS:
        key = '24h'
    return to_jsonable(compute_filter_compare(db, key))


@router.get('/api/ultron/watchlist')
def ultron_watchlist(
    days: int = 7, q: str = '', sector: str | None = None,
    city: str | None = None, experience: str | None = None,
    db: Session = Depends(get_db),
):
    if days not in ALLOWED_WINDOWS:
        days = 7
    sector = normalize_sector(sector)
    city = normalize_city_filter(city)
    experience = normalize_experience(experience)
    return {
        'days': days,
        'sector': sector or '',
        'city': city or '',
        'experience': experience or '',
        'sector_options': sector_options(),
        'city_options': city_options(),
        'experience_options': experience_options(),
        'window_options': [{'days': d, 'label': label} for d, label in WINDOW_OPTIONS],
        'q': q,
        'watched': to_jsonable(
            watchlist_rows(
                db, window_days=days, q=q, sector=sector, city=city,
                experience=experience,
            )
        ),
        'directory': to_jsonable(company_directory(db, q=q, limit=50)),
    }


@router.get('/api/ultron/roles/{search_id}/companies')
def ultron_role_companies(
    search_id: int,
    days: int = 7,
    city: str | None = None,
    sector: str | None = None,
    experience: str | None = None,
    db: Session = Depends(get_db),
):
    if days not in ALLOWED_WINDOWS:
        days = 7
    cfg = db.get(SearchConfig, search_id)
    if cfg is None:
        return JSONResponse({'ok': False, 'error': 'role not found'}, status_code=404)
    city = normalize_city_filter(city)
    sector = normalize_sector(sector)
    experience = normalize_experience(experience)
    role_name, companies = companies_for_role(
        db, search_id, window_days=days, city=city, sector=sector,
        experience=experience,
    )
    cities = cities_for_role(
        db, search_id, window_days=days, sector=sector, experience=experience,
    )
    max_n = max([c.recent for c in companies] + [1])
    max_city = max([c['n'] for c in cities] + [1])
    return {
        'ok': True,
        'search_id': search_id,
        'role': role_name,
        'days': days,
        'city': city or '',
        'sector': sector or '',
        'experience': experience or '',
        'city_options': city_options(),
        'sector_options': sector_options(),
        'experience_options': experience_options(),
        'window_options': [{'days': d, 'label': label} for d, label in WINDOW_OPTIONS],
        'max': max_n,
        'max_city': max_city,
        'companies': to_jsonable(companies),
        'cities': cities,
    }


@router.post('/api/ultron/watchlist/{company_id}/toggle')
def ultron_watchlist_toggle(company_id: int, db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if company is None:
        return JSONResponse({'ok': False, 'error': 'not found'}, status_code=404)
    watched = not bool(company.watched)
    set_watched(db, company_id, watched)
    return {'ok': True, 'company_id': company_id, 'watched': watched}


@router.get('/api/ultron/companies/{company_id}')
def ultron_company_profile(company_id: int, db: Session = Depends(get_db)):
    """Company embedding: logo, punchline, followers, employee size."""
    company = db.get(Company, company_id)
    if company is None:
        return JSONResponse({'ok': False, 'error': 'not found'}, status_code=404)
    return {
        'ok': True,
        'company_id': company.id,
        'name': company.name,
        'linkedin_url': company.linkedin_url,
        'logo_url': company.logo_url,
        'tagline': company.tagline,
        'punchline': company.punchline,
        'about_text': company.about_text,
        'follower_count': company.follower_count,
        'employee_count_min': company.employee_count_min,
        'employee_count_max': company.employee_count_max,
        'employee_count_label': company.employee_count_label,
        'watched': bool(company.watched),
        'profile_enriched_at': _iso(company.profile_enriched_at),
    }


@router.get('/api/ultron/health')
def ultron_health(db: Session = Depends(get_db)):
    vitals = compute_vitals(db)
    recent = db.execute(
        select(TowerEvent).order_by(desc(TowerEvent.id)).limit(40)
    ).scalars().all()
    return {
        'vitals': _vitals_json(vitals),
        'recent_events': [{
            'id': e.id,
            'kind': e.kind,
            'message': e.detail,
            'created_at': _iso(e.ts),
        } for e in recent],
    }


@router.get('/api/ultron/ai-capacity')
def ultron_ai_capacity(db: Session = Depends(get_db)):
    """Scrape-first mutex: Hermes / VIGIL Ask must check before using Ollama."""
    return compute_ai_capacity(db)


@router.get('/api/ultron/boards')
def ultron_boards_help():
    """List VIGIL Telegram/Ask board commands (deterministic, no LLM)."""
    return {'text': BOARD_HELP, 'boards': [
        'towerinsights', 'health', 'hiringsignals', 'searches',
        'watchlist', 'fresh', 'brief', 'help',
    ]}


@router.get('/api/ultron/boards/{name}')
def ultron_board(name: str, days: int | None = None):
    """Render a VIGIL board as plain text — same facts as the dashboard panels."""
    if resolve_board(name) is None and name.lower() not in (
        'tower', 'health', 'signals', 'searches', 'watchlist', 'fresh', 'brief', 'help',
    ):
        return JSONResponse({'ok': False, 'error': 'unknown board', 'text': BOARD_HELP}, status_code=404)
    text = render_board(name, days=days)
    return {'ok': True, 'board': resolve_board(name) or name, 'days': days, 'text': text}


@router.post('/api/ultron/ask')
def ultron_ask(payload: dict, db: Session = Depends(get_db)):
    """VIGIL Ask → board shortcut or Hermes (local Ollama), capacity-gated."""
    prompt = str(payload.get('prompt') or payload.get('q') or '')
    force = bool(payload.get('force'))
    return ask_hermes(db, prompt, force=force)


@router.post('/api/ultron/toggle-headless')
async def ultron_toggle_headless():
    val = not get_headless()
    set_headless(val)
    await hub.broadcast({
        'type': 'ultron.command',
        'command': 'toggle_headless',
        'headless': val,
    })
    return {
        'headless': val,
        'label': 'Hidden (cooler)' if val else 'Visible window',
    }


@router.post('/api/ultron/dismiss-alert')
async def ultron_dismiss_alert():
    dismiss_linkedin_block()
    await hub.broadcast({'type': 'ultron.command', 'command': 'dismiss_alert'})
    return {'ok': True}


@router.post('/api/ultron/training-log')
async def ultron_training_log(payload: dict):
    """Persist VIGIL training session logs for gesture tuning (Akay)."""
    data_dir = Path(__file__).resolve().parents[2] / '.data' / 'vigil_training'
    data_dir.mkdir(parents=True, exist_ok=True)
    sid = str(payload.get('id') or f'session-{datetime.now(timezone.utc).timestamp()}')
    safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in sid)[:80]
    path = data_dir / f'{safe}.json'
    path.write_text(json.dumps(payload, indent=2, default=str), encoding='utf-8')
    (data_dir / 'latest.json').write_text(
        json.dumps({'id': safe, 'path': str(path), 'at': _iso(datetime.now(timezone.utc))}),
        encoding='utf-8',
    )
    await hub.broadcast({'type': 'ultron.training_log', 'id': safe})
    return {'ok': True, 'id': safe, 'path': str(path)}


@router.get('/api/ultron/training-log/latest')
def ultron_training_log_latest():
    data_dir = Path(__file__).resolve().parents[2] / '.data' / 'vigil_training'
    latest = data_dir / 'latest.json'
    if not latest.exists():
        return JSONResponse({'ok': False, 'error': 'no logs yet'}, status_code=404)
    meta = json.loads(latest.read_text(encoding='utf-8'))
    path = Path(meta.get('path') or '')
    if not path.is_file():
        return JSONResponse({'ok': False, 'error': 'missing file'}, status_code=404)
    return json.loads(path.read_text(encoding='utf-8'))


@router.get('/api/ultron/director-traces')
def ultron_director_traces(limit: int = 40):
    """List DIRECTOR Telegram workflow traces (newest first) for audit."""
    from app.director.trace import list_traces
    rows = list_traces(limit=min(max(limit, 1), 100))
    return {'traces': rows, 'count': len(rows)}


@router.get('/api/ultron/director-traces/{trace_id}')
def ultron_director_trace(trace_id: str):
    """Full workflow nodes for one Telegram→DIRECTOR run."""
    from app.director.trace import get_trace
    safe = ''.join(c for c in trace_id if c.isalnum() or c in '-_')[:80]
    data = get_trace(safe)
    if not data:
        return JSONResponse({'ok': False, 'error': 'not found'}, status_code=404)
    return data


@router.post('/api/ultron/configs/{config_id}/run')
def ultron_run_config(config_id: int, db: Session = Depends(get_db)):
    cfg = db.get(SearchConfig, config_id)
    if cfg is None:
        return JSONResponse({'ok': False, 'error': 'not found'}, status_code=404)
    now = datetime.now(timezone.utc)
    if _config_busy(db, cfg.id):
        return JSONResponse({'ok': False, 'error': 'busy'}, status_code=409)
    run = ScrapeRun(
        search_config_id=cfg.id,
        run_type='one_off',
        scheduled_for=None,
        target_date=now.date(),
        status='dispatched',
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run_scrape.delay(run.id)
    return {'ok': True, 'run_id': run.id}


def mount_vigil_static(app) -> None:
    from fastapi.staticfiles import StaticFiles
    assets = VIGIL_DIST / 'assets'
    if assets.exists():
        app.mount('/assets', StaticFiles(directory=str(assets)), name='vigil-assets')
