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
    companies_for_role,
    company_directory,
    compute_hiring_signals,
    set_watched,
    watchlist_rows,
)
from app.ai_capacity import compute_ai_capacity
from app.filter_compare import ALLOWED_FILTER_WINDOWS, compute_filter_compare
from app.hermes_ask import ask_hermes
from app.role_analytics import roles_in_window
from app.sectors import CRITICAL_SECTORS
from app.tasks import _config_busy, run_scrape
from app.tower_health import compute_vitals
from app.ultron.hub import hub
from app.ultron.serialize import to_jsonable
from app.vigil_boards import BOARD_HELP, render_board, resolve_board

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


@router.get('/api/ultron/tower')
def ultron_tower(db: Session = Depends(get_db)):
    today = datetime.now(timezone.utc).date()
    week_ago = today - timedelta(days=7)
    top_companies = db.execute(
        select(Company.id, Company.name, func.count(JobMaster.id).label('n'))
        .join(JobMaster, JobMaster.company_id == Company.id)
        .where(JobMaster.posted_date >= week_ago)
        .group_by(Company.id, Company.name).order_by(desc('n')).limit(8)
    ).all()
    # Fair: same 7d window as top companies — early-started roles no longer dominate
    fair_roles = roles_in_window(db, days=7, limit=40, mode='count')
    per_role = fair_roles['roles']
    daily = dict(db.execute(
        select(JobMaster.posted_date, func.count(JobMaster.id))
        .where(JobMaster.posted_date >= today - timedelta(days=13))
        .group_by(JobMaster.posted_date)
    ).all())
    daily_series = [
        {'day': str(today - timedelta(days=13 - i)), 'n': daily.get(today - timedelta(days=13 - i), 0)}
        for i in range(14)
    ]
    latest = db.execute(
        select(JobMaster, Company.id, Company.name)
        .outerjoin(Company, JobMaster.company_id == Company.id)
        .order_by(desc(JobMaster.scraped_at)).limit(8)
    ).all()
    signals = compute_hiring_signals(db, window_days=7)
    watched = watchlist_rows(db, window_days=7)[:6]
    return {
        'stats': {
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
        },
        'top_companies': [
            {'company_id': cid, 'name': n, 'n': c} for cid, n, c in top_companies
        ],
        'per_role': per_role,
        'per_role_window_days': 7,
        'fair_hint': fair_roles.get('fair_hint'),
        'sectors': CRITICAL_SECTORS,
        'window_options': [{'days': d, 'label': label} for d, label in WINDOW_OPTIONS],
        'daily_series': daily_series,
        'latest_jobs': [{
            'id': j.id,
            'title': j.title,
            'company_id': cid,
            'company': cname,
            'location': j.location,
            'job_url': j.job_url,
            'scraped_at': _iso(j.scraped_at),
            'posted_date': str(j.posted_date) if j.posted_date else None,
        } for j, cid, cname in latest],
        'signals_teaser': to_jsonable(signals),
        'watched': to_jsonable(watched),
    }


@router.get('/api/ultron/top-companies')
def ultron_top_companies(days: int = 7, limit: int = 80, db: Session = Depends(get_db)):
    """Full company hiring ranking for Show all — max → min."""
    if days not in ALLOWED_WINDOWS:
        days = 7
    limit = max(1, min(limit, 200))
    _days, recent_start, recent_end, _ps, _pe, by_scraped = _window_bounds(days)
    time_col = JobMaster.scraped_at if by_scraped else JobMaster.posted_date
    rows = db.execute(
        select(Company.id, Company.name, func.count(JobMaster.id).label('n'))
        .join(JobMaster, JobMaster.company_id == Company.id)
        .where(time_col >= recent_start, time_col < recent_end)
        .group_by(Company.id, Company.name)
        .order_by(desc('n'))
        .limit(limit)
    ).all()
    max_n = max([n for _, _, n in rows] + [1])
    return {
        'days': days,
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
    db: Session = Depends(get_db),
):
    """Jobs-per-role ranking — windowed (fair) count or per-day rate."""
    return roles_in_window(db, days=days, limit=limit, mode=mode)


@router.get('/api/ultron/sectors')
def ultron_sectors():
    """Critical sector catalogue for UI filters and labels."""
    return {'sectors': CRITICAL_SECTORS}


@router.get('/api/ultron/signals')
def ultron_signals(days: int = 7, db: Session = Depends(get_db)):
    if days not in ALLOWED_WINDOWS:
        days = 7
    return {
        'days': days,
        'window_options': [{'days': d, 'label': label} for d, label in WINDOW_OPTIONS],
        'signals': to_jsonable(compute_hiring_signals(db, window_days=days)),
    }


@router.get('/api/ultron/filter-compare')
def ultron_filter_compare(window: str = '24h', db: Session = Depends(get_db)):
    """AI (Ollama) vs Keyword (Plan B) filter counts for a time window."""
    key = (window or '24h').strip().lower()
    if key not in ALLOWED_FILTER_WINDOWS:
        key = '24h'
    return to_jsonable(compute_filter_compare(db, key))


@router.get('/api/ultron/watchlist')
def ultron_watchlist(days: int = 7, q: str = '', db: Session = Depends(get_db)):
    if days not in ALLOWED_WINDOWS:
        days = 7
    return {
        'days': days,
        'window_options': [{'days': d, 'label': label} for d, label in WINDOW_OPTIONS],
        'q': q,
        'watched': to_jsonable(watchlist_rows(db, window_days=days, q=q)),
        'directory': to_jsonable(company_directory(db, q=q, limit=50)),
    }


@router.get('/api/ultron/roles/{search_id}/companies')
def ultron_role_companies(search_id: int, days: int = 7, db: Session = Depends(get_db)):
    if days not in ALLOWED_WINDOWS:
        days = 7
    cfg = db.get(SearchConfig, search_id)
    if cfg is None:
        return JSONResponse({'ok': False, 'error': 'role not found'}, status_code=404)
    role_name, companies = companies_for_role(db, search_id, window_days=days)
    max_n = max([c.recent for c in companies] + [1])
    return {
        'ok': True,
        'search_id': search_id,
        'role': role_name,
        'days': days,
        'window_options': [{'days': d, 'label': label} for d, label in WINDOW_OPTIONS],
        'max': max_n,
        'companies': to_jsonable(companies),
    }


@router.post('/api/ultron/watchlist/{company_id}/toggle')
def ultron_watchlist_toggle(company_id: int, db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if company is None:
        return JSONResponse({'ok': False, 'error': 'not found'}, status_code=404)
    watched = not bool(company.watched)
    set_watched(db, company_id, watched)
    return {'ok': True, 'company_id': company_id, 'watched': watched}


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
