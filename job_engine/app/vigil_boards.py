"""VIGIL board text — same facts as the dashboard, plain Telegram layout.

No LLM. Pure HTTP reads of the local Ultron API.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from app.telegram_voice import VoiceLayer

BASE = 'http://127.0.0.1:8001'
BRIEF = Path('/home/user/Documents/documents/briefs/latest.txt')

# Slash / alias → board id
ALIASES = {
    'tower': 'tower',
    'towerinsights': 'tower',
    'insights': 'tower',
    'health': 'health',
    'towerhealth': 'health',
    'signals': 'signals',
    'hiringsignals': 'signals',
    'hiring': 'signals',
    'searches': 'searches',
    'roles': 'searches',
    'watchlist': 'watchlist',
    'watched': 'watchlist',
    'fresh': 'fresh',
    'freshest': 'fresh',
    'catches': 'fresh',
    'brief': 'brief',
    'dailybrief': 'brief',
    'help': 'help',
    'boards': 'help',
    'menu': 'help',
}

BOARD_HELP = """VIGIL boards (live tower data — no guessing)

/towerinsights — Tower Insights
/health — Tower health
/hiringsignals — Hiring signals (7d)
/hiringsignals 0 — signals last 24h (0=24h · 1=today · 2 · 4 · 7 · 14 · 30)
/searches — Roles / searches
/watchlist — Watched companies
/fresh — Freshest catches
/brief — Daily hiring brief

Ask in plain words only after a board; numbers must match the tower."""


def _get(path: str, params: dict | None = None):
    url = BASE + path
    if params:
        url += '?' + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _bar(n: int, max_n: int, width: int = 10) -> str:
    if max_n <= 0:
        return '·' * width
    filled = max(1, round((n / max_n) * width)) if n else 0
    return '█' * filled + '░' * (width - filled)


def _company_name(j: dict) -> str:
    c = j.get('company')
    if isinstance(c, dict):
        return c.get('name') or '—'
    return c or '—'


def resolve_board(name: str) -> str | None:
    key = (name or '').strip().lstrip('/').lower().replace('-', '').replace('_', '')
    return ALIASES.get(key)


def render_board(board: str, *, days: int | None = None, unfiltered: bool = False) -> str:
    bid = resolve_board(board) or (board or '').strip().lower()
    try:
        if bid == 'help':
            return BOARD_HELP
        if bid == 'tower':
            return _board_tower()
        if bid == 'health':
            return _board_health()
        if bid == 'signals':
            return _board_signals(days if days is not None else 7)
        if bid == 'searches':
            return _board_searches()
        if bid == 'watchlist':
            return _board_watchlist(days if days is not None else 7)
        if bid == 'fresh':
            return _board_fresh(unfiltered=unfiltered)
        if bid == 'brief':
            return _board_brief()
    except urllib.error.URLError as e:
        return f'Tower API unreachable ({e}). Is Watch Tower running?'
    except Exception as e:
        return f'Board failed: {e}'
    return f'Unknown board "{board}".\n\n{BOARD_HELP}'


def _board_tower() -> str:
    d = _get('/api/ultron/tower')
    s = d.get('stats') or {}
    top = d.get('top_companies') or []
    roles = (d.get('per_role') or [])[:8]
    latest = d.get('latest_jobs') or []
    max_c = max((c.get('n') or 0 for c in top), default=1)
    max_r = max((r.get('n') or 0 for r in roles), default=1)
    lines = [
        'TOWER INSIGHTS',
        f"Jobs {s.get('total_jobs', '—')} · Today {s.get('jobs_today', '—')} · "
        f"Companies {s.get('companies', '—')} · Active {s.get('runs_active', '—')}",
        '',
        'Top hiring (7d)',
    ]
    for c in top:
        n = c.get('n') or 0
        lines.append(f"  {_bar(n, max_c)}  {c.get('name')} — {n}")
    lines += ['', 'Jobs per role']
    for r in roles:
        n = r.get('n') or 0
        lines.append(f"  {_bar(n, max_r)}  {r.get('name')} — {n}")
    lines += ['', 'Freshest catches']
    for j in latest[:8]:
        when = j.get('posted_date') or '—'
        lines.append(f"  · {j.get('title')}")
        lines.append(f"    {_company_name(j)} · {when}")
    return '\n'.join(lines)


def _voice_status_label() -> str:
    """Cheap local check (no network, no model call) so /health tells Ashok on
    this laptop whether the JobMaster voice layer (LLM warmth pass) can
    actually run — he can't see the .env from Telegram."""
    flag_on = os.getenv('JOBMASTER_VOICE_LLM', 'true').strip().lower() == 'true'
    if not flag_on:
        return 'OFF (disabled via JOBMASTER_VOICE_LLM)'
    if VoiceLayer().enabled:
        return 'ON (OPENAI_API_KEY set)'
    return 'OFF (no OPENAI_API_KEY)'


def _rel_age(iso: str | None) -> str:
    """'26h ago' style age so a stale pulse can never masquerade as live.

    The 2026-08-13 stall looked alive on Telegram exactly because /health
    printed day-old ollama pulses with no timestamps.
    """
    if not iso:
        return ''
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return ''
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
    if secs < 90:
        return 'just now'
    if secs < 5400:
        return f'{int(secs // 60)}m ago'
    hours = secs / 3600
    if hours < 48:
        return f'{int(hours)}h ago'
    return f'{int(hours // 24)}d ago'


def _board_health() -> str:
    d = _get('/api/ultron/health')
    v = d.get('vitals') or d
    heat = v.get('heat_c')
    heat_s = f'{round(heat)}°' if heat is not None else '—'
    lines = [
        'TOWER HEALTH',
        f"Heat {heat_s} ({v.get('heat_label', '—')}) · Memory {round(v.get('mem_pct') or 0)}% · "
        f"CPU {v.get('cpu_label', '—')}",
        f"Searches today {v.get('searches_today', '—')} · 24h {v.get('searches_24h', '—')}",
        f"Ollama today {v.get('ollama_today', '—')} · 24h {v.get('ollama_24h', '—')} · "
        f"capacity ~{v.get('ollama_capacity_estimate', '—')}/day",
        f"Mode {v.get('filter_mode_policy', '—')} · Browser {'Hidden' if v.get('headless') else 'Visible'}",
        f"Now: {v.get('countdown_title') or v.get('next_search_label') or '—'}",
        f"Alert: {v.get('alert_label') or '—'}",
        f"JobMaster voice AI: {_voice_status_label()}",
    ]
    if v.get('stall_detail'):
        lines.append(f"Stalled: {v['stall_detail']}")
    if v.get('planb_detail'):
        lines.append(f"Plan B: {v['planb_detail']}")
    events = d.get('recent_events') or []
    if events:
        lines.append('')
        lines.append('Recent pulses')
        for e in events[:8]:
            age = _rel_age(e.get('created_at'))
            suffix = f' · {age}' if age else ''
            lines.append(f"  · {e.get('kind')}: {(e.get('message') or '')[:80]}{suffix}")
    return '\n'.join(lines)


def _board_signals(days: int) -> str:
    d = _get('/api/ultron/signals', {'days': days})
    s = d.get('signals') or {}
    label = next((w.get('label') for w in (d.get('window_options') or []) if w.get('days') == days), f'{days}d')
    lines = [
        f'HIRING SIGNALS · {label}',
        f"Recent {s.get('recent_total', '—')} · Prior {s.get('prior_total', '—')}",
        s.get('headline') or 'No signal yet.',
        '',
        'Growing roles',
    ]
    for r in (s.get('growing_roles') or [])[:8]:
        delta = r.get('delta')
        if delta is None and r.get('recent') is not None and r.get('prior') is not None:
            delta = int(r['recent']) - int(r['prior'])
        lines.append(f"  · {r.get('name')} — {r.get('recent')} recent (+{delta})")
    lines += ['', 'Fastest companies']
    for c in (s.get('fastest_companies') or [])[:8]:
        delta = c.get('delta')
        if delta is None and c.get('recent') is not None and c.get('prior') is not None:
            delta = int(c['recent']) - int(c['prior'])
        lines.append(f"  · {c.get('name')} — {c.get('recent')} recent (+{delta})")
    return '\n'.join(lines)


def _board_searches() -> str:
    configs = _get('/api/configs')
    if not isinstance(configs, list):
        return 'Searches unavailable.'
    on = [c for c in configs if c.get('enabled')]
    off = [c for c in configs if not c.get('enabled')]
    lines = [
        'SEARCHES',
        f'{len(configs)} roles · {len(on)} on · {len(off)} paused',
        '',
    ]
    for c in on[:40]:
        lines.append(f"  · {c.get('name')} — On")
        lines.append(f"    {c.get('keywords')} · {c.get('location_label') or '—'}")
    if len(on) > 40:
        lines.append(f'  … +{len(on) - 40} more on')
    if off:
        lines.append('')
        lines.append('Paused')
        for c in off[:15]:
            lines.append(f"  · {c.get('name')}")
    return '\n'.join(lines)


def _board_watchlist(days: int) -> str:
    d = _get('/api/ultron/watchlist', {'days': days})
    watched = d.get('watched') or []
    lines = [f'WATCHLIST · {days}d window' if days else 'WATCHLIST', '']
    if not watched:
        lines.append('No watched companies yet — star them in VIGIL Watchlist.')
        return '\n'.join(lines)
    for c in watched[:20]:
        lines.append(
            f"  · {c.get('name')} — recent {c.get('recent')} / prior {c.get('prior')}"
        )
    return '\n'.join(lines)


def _board_fresh(unfiltered: bool = False) -> str:
    # Checked-only law (2026-08-14): the board lists detail-verified jobs
    # unless the command carried '-unfiltered'.
    if unfiltered:
        d = _get('/api/ultron/tower')
        latest = d.get('latest_jobs') or []
    else:
        latest = _get('/api/jobs', {'limit': 12, 'verified': 1})
        latest = latest if isinstance(latest, list) else []
    title = 'FRESHEST CATCHES' + ('' if unfiltered else ' · checked')
    lines = [title, '']
    if not latest:
        lines.append(
            'No catches yet — tower is still collecting.'
            if unfiltered else
            'No checked catches yet — verification is catching up. '
            'Send /fresh -unfiltered to see raw catches.'
        )
        return '\n'.join(lines)
    for i, j in enumerate(latest[:12], 1):
        lines.append(f"{i}. {j.get('title')}")
        lines.append(f"   {_company_name(j)} · {j.get('location') or '—'}")
        lines.append(f"   posted {j.get('posted_date') or '—'} · scraped {j.get('scraped_at') or '—'}")
        if j.get('job_url'):
            lines.append(f"   {j['job_url']}")
    return '\n'.join(lines)


def _board_brief() -> str:
    if BRIEF.exists():
        return BRIEF.read_text(encoding='utf-8').strip()
    # generate via same HTTP path as daily brief script logic (inline)
    return render_board('tower') + '\n\n(No saved daily brief yet — Tower Insights above.)'
