"""STAGEHAND tools — live Watch Tower facts (Ultron HTTP). Never invent numbers."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from agents import function_tool

from app.cities import city_label, normalize_city_filter

BASE = 'http://127.0.0.1:8001'

# AI role match — word-ish tokens; never bare "AI" inside Apprentice
_AI_TITLE_RE = re.compile(
    r'(?i)(?<![a-z])(?:'
    r'ai/?ml|a\.?i\.?|artificial\s+intelligence|machine\s+learning|'
    r'\bml\b|llm|genai|generative\s+ai|deep\s+learning|nlp\b|computer\s+vision'
    r')(?![a-z])'
)


def _get(path: str, params: dict | None = None) -> dict | list:
    url = BASE + path
    if params:
        clean = {k: v for k, v in params.items() if v is not None and v != ''}
        if clean:
            url += '?' + urllib.parse.urlencode(clean)
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _resolve_city(city: str) -> tuple[str | None, str]:
    """Return (city_key or None, human label). None key = all cities only if city blank."""
    raw = (city or '').strip()
    if not raw:
        return None, 'All cities'
    key = normalize_city_filter(raw)
    if key is None:
        # Unknown city name — do not silently widen to all India
        return '__unknown__', raw
    return key, city_label(key)


def _is_ai_title(title: str) -> bool:
    """True for AI/ML roles. Scrub 'Apprentice' so it cannot fake an AI hit."""
    scrubbed = re.sub(r'(?i)apprentice', '', title or '')
    if _AI_TITLE_RE.search(scrubbed):
        return True
    if re.search(r'(?i)(?:^|[^a-z])ai(?:[^a-z]|$)', scrubbed):
        return True
    if re.search(r'(?i)(?:^|[^a-z])ml(?:[^a-z]|$)', scrubbed):
        return True
    return False


@function_tool
def stagehand_tower_stats() -> str:
    """STAGEHAND: Live ALL-INDIA tower KPIs — total jobs, jobs today, companies.
    Do NOT use this for a city question (Bangalore etc). Use stagehand_city_pulse instead."""
    tower = _get('/api/ultron/tower')
    stats = tower.get('stats') or {}
    top = (tower.get('top_companies') or [])[:5]
    roles = (tower.get('per_role') or [])[:5]
    return json.dumps({
        'scope': 'all_india',
        'total_jobs': stats.get('total_jobs'),
        'jobs_today': stats.get('jobs_today'),
        'companies': stats.get('companies'),
        'top_companies': top,
        'jobs_per_role': roles,
        'warning': 'These numbers are NOT city-scoped.',
    }, ensure_ascii=False)


@function_tool
def stagehand_tower_heat() -> str:
    """STAGEHAND: Live ThinkPad / tower heat — CPU°C, GPU°C, heat label, load, phase."""
    data = _get('/api/ultron/health')
    v = (data or {}).get('vitals') or {}
    return json.dumps({
        'heat_c': v.get('heat_c'),
        'heat_label': v.get('heat_label'),
        'heat_detail': v.get('heat_detail'),
        'mem_pct': v.get('mem_pct'),
        'phase_label': v.get('phase_label'),
        'scrape_running_name': v.get('scrape_running_name'),
        'ollama_live': v.get('ollama_live'),
        'filter_mode_policy': v.get('filter_mode_policy'),
        'next_search_label': v.get('next_search_label'),
    }, ensure_ascii=False)


@function_tool
def stagehand_city_pulse(city: str = 'bengaluru') -> str:
    """STAGEHAND: City-scoped pulse — jobs in city, companies in city, jobs scraped today in city.
    ALWAYS call this for Bangalore/Bengaluru/Chennai/etc questions.
    Accepts aliases (bangalore→bengaluru). Never invent city totals."""
    key, label = _resolve_city(city)
    if key == '__unknown__':
        return json.dumps({
            'ok': False,
            'error': f'Unknown city {label!r}. Use bengaluru, chennai, hyderabad, pune, mumbai, delhi, gurugram, noida, kerala, remote.',
        })
    params = {}
    if key:
        params['city'] = key
    tower = _get('/api/ultron/tower', params)
    stats = tower.get('stats') or {}
    top = (tower.get('top_companies') or [])[:5]
    roles = (tower.get('per_role') or [])[:8]
    return json.dumps({
        'ok': True,
        'scope': 'city',
        'city_key': key or 'all',
        'city_label': label,
        'total_jobs': stats.get('total_jobs'),
        'jobs_today': stats.get('jobs_today'),
        'companies': stats.get('companies'),
        'top_companies': top,
        'jobs_per_role': roles,
    }, ensure_ascii=False)


@function_tool
def stagehand_hiring_signals(days: int = 0, city: str = '') -> str:
    """STAGEHAND: Hiring signals — rising roles / company velocity.
    Pass city (bengaluru/bangalore/…) to scope; empty city = all India.
    days: 0=24h, 1=today, 7=week."""
    key, label = _resolve_city(city) if city.strip() else (None, 'All cities')
    if key == '__unknown__':
        return json.dumps({'ok': False, 'error': f'Unknown city {label!r}'})
    params: dict = {'days': days}
    if key:
        params['city'] = key
    data = _get('/api/ultron/signals', params)
    sig = data.get('signals') or data
    return json.dumps({
        'ok': True,
        'scope': 'city' if key else 'all_india',
        'city_key': key or 'all',
        'city_label': label,
        'headline': sig.get('headline'),
        'growing_roles': (sig.get('growing_roles') or [])[:8],
        'fastest_companies': (sig.get('fastest_companies') or [])[:8],
    }, ensure_ascii=False)


@function_tool
def stagehand_search_jobs(title: str = '', city: str = '', limit: int = 40) -> str:
    """STAGEHAND: Search indexed jobs by title and/or city.
    City aliases normalized (bangalore→bengaluru). Unknown city → error (no silent all-India)."""
    key, label = _resolve_city(city) if city.strip() else (None, 'All cities')
    if key == '__unknown__':
        return json.dumps({'ok': False, 'error': f'Unknown city {label!r}', 'jobs': []})
    params: dict = {'limit': min(max(limit, 1), 200)}
    if title:
        params['title'] = title
    if key:
        params['city'] = key
    jobs = _get('/api/jobs', params)
    if not isinstance(jobs, list):
        return json.dumps({'ok': False, 'error': 'bad_response', 'jobs': []})
    tallies: dict[str, int] = {}
    samples = []
    for j in jobs:
        co = (j.get('company') or j.get('company_name') or 'Unknown').strip()
        tallies[co] = tallies.get(co, 0) + 1
        if len(samples) < 15:
            samples.append({
                'title': j.get('title'),
                'company': co,
                'city_key': j.get('city_key'),
                'posted_date': str(j.get('posted_date') or ''),
            })
    ranked = sorted(tallies.items(), key=lambda x: (-x[1], x[0]))[:15]
    return json.dumps({
        'ok': True,
        'scope': 'city' if key else 'all_india',
        'city_key': key or 'all',
        'city_label': label,
        'match_count': len(jobs),
        'companies': [{'name': n, 'n': c} for n, c in ranked],
        'samples': samples,
    }, ensure_ascii=False)


@function_tool
def stagehand_ai_jobs(city: str = 'bengaluru', limit: int = 12) -> str:
    """STAGEHAND: AI / ML roles only in a city (strict title match — not Apprentice false positives).
    Use for 'AI jobs in Bangalore' style asks. Returns exact jobs for a text fact board."""
    key, label = _resolve_city(city)
    if key == '__unknown__' or not key:
        return json.dumps({
            'ok': False,
            'error': 'Need a known city (e.g. bengaluru / bangalore).',
        })
    jobs = _get('/api/jobs', {'city': key, 'limit': 300})
    if not isinstance(jobs, list):
        return json.dumps({'ok': False, 'error': 'bad_response'})
    ai = []
    for j in jobs:
        title = j.get('title') or ''
        if not _is_ai_title(title):
            continue
        ai.append({
            'title': title,
            'company': (j.get('company') or j.get('company_name') or '').strip(),
            'city_key': j.get('city_key'),
            'posted_date': str(j.get('posted_date') or ''),
        })
        if len(ai) >= min(limit, 20):
            break
    return json.dumps({
        'ok': True,
        'scope': 'city',
        'city_key': key,
        'city_label': label,
        'match_count': len(ai),
        'note': 'Strict AI/ML title match; Apprentice alone is excluded.',
        'jobs': ai,
    }, ensure_ascii=False)


@function_tool
def stagehand_watchlist(days: int = 7) -> str:
    """STAGEHAND: Watched companies pulse for the given day window."""
    data = _get('/api/ultron/watchlist', {'days': days})
    watched = (data.get('watched') or [])[:8]
    return json.dumps({'watched': watched}, ensure_ascii=False)
