"""Deterministic guest job-listing replies — NO LLM in this path.

Ashok 2026-08-04 (guest soul v2): the LLM guest agent kept drifting —
made-up salary bands, "typical employers" speculation, zero links, chatty
generic-assistant greetings. Boards fixed this exact hallucination problem
for the owner path back on 2026-08-02 by going deterministic-text-only; same
medicine here. Every job listed comes straight from the tower API with its
real job_url — no LLM ever touches the wording of a job row.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from app.cities import city_label, normalize_city_filter

BASE = 'http://127.0.0.1:8001'
MAX_ROWS = 8

_GREETING_RE = re.compile(r'^\s*(hi+|hello+|hey+|yo|sup|start|/start|namaste)\b', re.I)

_FILLER_WORDS = re.compile(
    r'\b('
    r'jobs?|openings?|opening|vacanc(?:y|ies)|role|roles|hiring|any|'
    r'is\s+there|are\s+there|please|pls|show\s+me|find\s+me|looking\s+for|'
    r'i\s+want|i\s+need|near\s+me|today|now|current|latest|fresh(?:est)?|'
    r'catches?|for|in|at|of|the|an?|list|give\s+me'
    r')\b',
    re.I,
)


def _get(path: str, params: dict | None = None) -> dict | list:
    url = BASE + path
    if params:
        clean = {k: v for k, v in params.items() if v not in (None, '')}
        if clean:
            url += '?' + urllib.parse.urlencode(clean)
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _extract_city(text: str) -> tuple[str | None, str]:
    low = (text or '').lower()
    for word in re.findall(r'[a-zA-Z]+', low):
        key = normalize_city_filter(word)
        if key:
            return key, city_label(key)
    return None, ''


def _extract_role(text: str, city_key: str | None) -> str:
    low = (text or '').lower()
    if city_key:
        for word in re.findall(r'[a-zA-Z]+', low):
            if normalize_city_filter(word) == city_key:
                low = re.sub(rf'\b{re.escape(word)}\b', ' ', low)
    role = _FILLER_WORDS.sub(' ', low)
    role = re.sub(r'\s+', ' ', role).strip(' -,.?!')
    return role


def _fetch_jobs(role: str, city_key: str | None, limit: int = 60) -> list[dict]:
    try:
        params: dict = {'limit': limit}
        if role:
            params['title'] = role
        if city_key:
            params['city'] = city_key
        data = _get('/api/jobs', params)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _tower_line(city_key: str | None, city_lbl: str) -> str:
    try:
        tower = _get('/api/ultron/tower', {'city': city_key} if city_key else None)
        stats = (tower or {}).get('stats') or {}
        scope = city_lbl or 'India'
        today = int(stats.get('jobs_today') or 0)
        total = int(stats.get('total_jobs') or 0)
        companies = int(stats.get('companies') or 0)
        return f'{scope} · {today:,} jobs today · {total:,} in window · {companies:,} companies'
    except Exception:
        return ''


def _format_rows(jobs: list[dict], limit: int = MAX_ROWS) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for j in jobs:
        title = (j.get('title') or '').strip()
        company = (j.get('company') or j.get('company_name') or '').strip()
        url = (j.get('job_url') or '').strip()
        if not title or not url:
            continue  # no link, no listing — Ashok 2026-08-04
        key = f'{title.lower()}|{company.lower()}'
        if key in seen:
            continue
        seen.add(key)
        city_lbl = city_label(j.get('city_key')) if j.get('city_key') else ''
        head = f'{len(rows) + 1}. {title}'
        if company:
            head += f' — {company}'
        if city_lbl and city_lbl not in ('—', 'Other'):
            head += f' — {city_lbl}'
        rows.append(f'{head}\n{url}')
        if len(rows) >= limit:
            break
    return rows


def build_guest_reply(text: str) -> str:
    """Pure function: raw guest message -> ready-to-send Telegram text."""
    raw = (text or '').strip()
    city_key, city_lbl = _extract_city(raw)
    role = '' if _GREETING_RE.match(raw) else _extract_role(raw, city_key)

    scope_bit = f' in {city_lbl}' if city_lbl else ' across India'
    if role:
        jobs = _fetch_jobs(role, city_key, limit=60)
        header = f'{role.title()} jobs{scope_bit}:'
    else:
        jobs = _fetch_jobs('', city_key, limit=60)
        header = f'Freshest TECH openings{scope_bit}:'

    rows = _format_rows(jobs)
    parts = [header]
    line = _tower_line(city_key, city_lbl)
    if line:
        parts.append(line)
    parts.append('')

    if rows:
        parts.append('\n\n'.join(rows))
    else:
        fallback = _format_rows(_fetch_jobs('', None, limit=40), limit=5)
        parts.append('No exact matches right now for that search.')
        if fallback:
            parts.append('')
            parts.append('Fresh openings across India meanwhile:')
            parts.append('\n\n'.join(fallback))

    parts.append('')
    parts.append('Send another role or city anytime — e.g. "data analyst jobs in Pune".')
    return '\n'.join(p for p in parts if p is not None).strip()
