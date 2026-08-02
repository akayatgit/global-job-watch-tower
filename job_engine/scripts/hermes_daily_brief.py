#!/usr/bin/env python3
"""Daily hiring brief from live Watch Tower APIs (no Ollama required).

Stdout is the brief — Hermes cron can deliver to Telegram / local.
Safe on a hot ThinkPad: pure HTTP reads, never fights the scrape filter.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = 'http://127.0.0.1:8001'
OUT_DIR = Path('/home/user/Documents/documents/briefs')
TZ = ZoneInfo('Asia/Kolkata')


def get(path: str, params: dict | None = None):
    url = BASE + path
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))


def main() -> int:
    now = datetime.now(TZ)
    try:
        cap = get('/api/ultron/ai-capacity')
        tower = get('/api/ultron/tower')
        sig24 = get('/api/ultron/signals', {'days': 0})
        sig7 = get('/api/ultron/signals', {'days': 7})
        watch = get('/api/ultron/watchlist', {'days': 7})
    except Exception as e:
        print(f'Watch Tower brief failed — API unreachable ({e}).', file=sys.stderr)
        return 1

    stats = tower.get('stats') or {}
    s24 = sig24.get('signals') or {}
    s7 = sig7.get('signals') or {}
    top = (tower.get('top_companies') or [])[:5]
    roles = (tower.get('per_role') or [])[:5]
    watched = (watch.get('watched') or [])[:5]
    growing = (s24.get('growing_roles') or s7.get('growing_roles') or [])[:3]

    lines = [
        f'WATCH TOWER DAILY BRIEF · {now.strftime("%Y-%m-%d %H:%M IST")}',
        '',
        f'Jobs indexed: {stats.get("total_jobs", "—")} · Today: {stats.get("jobs_today", "—")} · '
        f'Companies: {stats.get("companies", "—")} · Active searches: {stats.get("runs_active", "—")}',
        '',
        f'Last 24h: {s24.get("headline") or "no signal yet"}',
        f'Last 7d: {s7.get("headline") or "no signal yet"}',
        '',
        'Top hiring (7d):',
    ]
    for c in top:
        lines.append(f'  · {c.get("name")} — {c.get("n")}')
    lines.append('')
    lines.append('Jobs per role:')
    for r in roles:
        lines.append(f'  · {r.get("name")} — {r.get("n")}')
    if growing:
        lines.append('')
        lines.append('Rising roles (signal window):')
        for r in growing:
            d = r.get('delta')
            if d is None and r.get('recent') is not None and r.get('prior') is not None:
                d = int(r['recent']) - int(r['prior'])
            lines.append(f'  · {r.get("name")} (+{d if d is not None else "?"})')
    if watched:
        lines.append('')
        lines.append('Watchlist pulse:')
        for c in watched:
            lines.append(f'  · {c.get("name")} — recent {c.get("recent")} / prior {c.get("prior")}')
    lines += [
        '',
        f'Tower AI capacity: {"READY" if cap.get("allowed") else "BUSY"} — {cap.get("reason", "")}',
        'Next: open VIGIL → Tower / Hiring Signals for drill-down.',
    ]
    brief = '\n'.join(lines)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f'brief-{now.strftime("%Y%m%d")}.txt'
    path.write_text(brief + '\n', encoding='utf-8')
    latest = OUT_DIR / 'latest.txt'
    latest.write_text(brief + '\n', encoding='utf-8')
    print(brief)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
