#!/usr/bin/env python3
"""Watch Tower MCP — read-only tools for Hermes / VIGIL Ask.

Talks to the local Ultron API only. No scrape control, no secrets.
Run via Hermes stdio MCP (see ~/.hermes/config.yaml mcp_servers.watch_tower).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from mcp.server.fastmcp import FastMCP

BASE = 'http://127.0.0.1:8001'
mcp = FastMCP(
    'watch-tower',
    instructions=(
        'Read-only Global Job WATCH TOWER tools. Prefer these over guesses. '
        'Call ai_capacity / tower_health before long answers. Never invent counts.'
    ),
)


def _get(path: str, params: dict | None = None) -> dict | list:
    url = BASE + path
    if params:
        url += '?' + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')[:500]
        return {'ok': False, 'error': f'HTTP {e.code}', 'detail': body}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _dump(data) -> str:
    return json.dumps(data, indent=2, default=str)[:12000]


@mcp.tool()
def ai_capacity() -> str:
    """Check if Hermes/Ask may use Ollama now. Scrape always wins — if busy, wait."""
    return _dump(_get('/api/ultron/ai-capacity'))


@mcp.tool()
def tower_health() -> str:
    """PC heat, memory, Ollama live flag, searches today — tower vitals."""
    data = _get('/api/ultron/health')
    if isinstance(data, dict) and 'vitals' in data:
        return _dump({'vitals': data['vitals']})
    return _dump(data)


@mcp.tool()
def tower_stats() -> str:
    """Tower overview: KPIs, top companies, jobs per role, freshest catches."""
    data = _get('/api/ultron/tower')
    if not isinstance(data, dict):
        return _dump(data)
    # Trim for context
    slim = {
        'stats': data.get('stats'),
        'top_companies': (data.get('top_companies') or [])[:12],
        'per_role': (data.get('per_role') or [])[:12],
        'latest_jobs': (data.get('latest_jobs') or [])[:8],
        'window_options': data.get('window_options'),
    }
    return _dump(slim)


@mcp.tool()
def hiring_signals(days: int = 7) -> str:
    """Hiring signals for a window. days: 0=24h, 1=today, 2,4,7,14,30."""
    return _dump(_get('/api/ultron/signals', {'days': days}))


@mcp.tool()
def watchlist(days: int = 7, q: str = '') -> str:
    """Watched companies with recent/prior opening counts."""
    return _dump(_get('/api/ultron/watchlist', {'days': days, 'q': q or ''}))


@mcp.tool()
def top_companies(days: int = 7, limit: int = 40) -> str:
    """Companies hiring ranked max→min in the window."""
    return _dump(_get('/api/ultron/top-companies', {'days': days, 'limit': limit}))


@mcp.tool()
def roles_rank(limit: int = 80) -> str:
    """All roles ranked by job count max→min."""
    return _dump(_get('/api/ultron/roles-rank', {'limit': limit}))


@mcp.tool()
def role_companies(search_id: int, days: int = 7) -> str:
    """Companies hiring for one role (search_id), max→min."""
    return _dump(_get(f'/api/ultron/roles/{search_id}/companies', {'days': days}))


@mcp.tool()
def search_jobs(
    limit: int = 40,
    company_id: int | None = None,
    search_config_id: int | None = None,
    company: str | None = None,
    title: str | None = None,
) -> str:
    """Search recent jobs. Optional filters: company_id, search_config_id, company name, title."""
    params = {
        'limit': limit,
        'company_id': company_id,
        'search_config_id': search_config_id,
        'company': company,
        'title': title,
    }
    return _dump(_get('/api/jobs', params))


if __name__ == '__main__':
    mcp.run(transport='stdio')
