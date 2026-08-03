"""STAGEHAND tools — live Watch Tower facts (Ultron HTTP). Never invent numbers."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from agents import function_tool

BASE = 'http://127.0.0.1:8001'


def _get(path: str, params: dict | None = None) -> dict | list:
    url = BASE + path
    if params:
        clean = {k: v for k, v in params.items() if v is not None and v != ''}
        if clean:
            url += '?' + urllib.parse.urlencode(clean)
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))


@function_tool
def stagehand_tower_stats() -> str:
    """STAGEHAND: Live tower KPIs — total jobs, jobs today, companies, freshest top hirers/roles.
    Call before stating any opening counts."""
    tower = _get('/api/ultron/tower')
    stats = tower.get('stats') or {}
    top = (tower.get('top_companies') or [])[:5]
    roles = (tower.get('per_role') or [])[:5]
    return json.dumps({
        'total_jobs': stats.get('total_jobs'),
        'jobs_today': stats.get('jobs_today'),
        'companies': stats.get('companies'),
        'top_companies': top,
        'jobs_per_role': roles,
    }, ensure_ascii=False)


@function_tool
def stagehand_hiring_signals(days: int = 0) -> str:
    """STAGEHAND: Hiring signals — headline, rising roles, company velocity.
    days: 0=24h, 1=today, 7=week, etc."""
    data = _get('/api/ultron/signals', {'days': days})
    sig = data.get('signals') or data
    return json.dumps({
        'headline': sig.get('headline'),
        'growing_roles': (sig.get('growing_roles') or [])[:5],
        'fastest_companies': (sig.get('fastest_companies') or [])[:5],
    }, ensure_ascii=False)


@function_tool
def stagehand_search_jobs(title: str = '', city: str = '', limit: int = 30) -> str:
    """STAGEHAND: Search indexed jobs by title and/or city key
    (bengaluru, chennai, hyderabad, pune, mumbai, delhi, gurugram, noida, kerala, remote).
    Returns company + title + posted_date samples and company tallies."""
    params = {'limit': min(limit, 80)}
    if title:
        params['title'] = title
    if city:
        params['city'] = city
    jobs = _get('/api/jobs', params)
    if not isinstance(jobs, list):
        return json.dumps({'error': 'bad_response', 'jobs': []})
    tallies: dict[str, int] = {}
    samples = []
    for j in jobs[:limit]:
        co = (j.get('company') or j.get('company_name') or 'Unknown').strip()
        tallies[co] = tallies.get(co, 0) + 1
        if len(samples) < 12:
            samples.append({
                'title': j.get('title'),
                'company': co,
                'city_key': j.get('city_key'),
                'posted_date': str(j.get('posted_date') or ''),
            })
    ranked = sorted(tallies.items(), key=lambda x: (-x[1], x[0]))[:15]
    return json.dumps({
        'match_count': len(jobs),
        'companies': [{'name': n, 'n': c} for n, c in ranked],
        'samples': samples,
    }, ensure_ascii=False)


@function_tool
def stagehand_watchlist(days: int = 7) -> str:
    """STAGEHAND: Watched companies pulse for the given day window."""
    data = _get('/api/ultron/watchlist', {'days': days})
    watched = (data.get('watched') or [])[:8]
    return json.dumps({'watched': watched}, ensure_ascii=False)
