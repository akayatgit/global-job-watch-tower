"""VALIDATOR — authenticity gate before any image / fact-board send.

Approves only when proposed numbers/rows match live STAGEHAND truth.
On reject, DIRECTOR must re-fetch and retry; courier_ack keeps Ashok waiting informed.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any

from agents import function_tool

from app.cities import city_label, normalize_city_filter
from app.director.trace import current_trace

BASE = 'http://127.0.0.1:8001'
MAX_VALIDATOR_ROUNDS = 4


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
    raw = (city or '').strip()
    if not raw:
        return None, 'All cities'
    key = normalize_city_filter(raw)
    if key is None:
        return '__unknown__', raw
    return key, city_label(key)


def _tower_stats(city: str = '') -> dict:
    key, label = _resolve_city(city) if city else (None, 'All cities')
    if key == '__unknown__':
        return {'ok': False, 'error': f'unknown city {label}'}
    params = {'city': key} if key else {}
    tower = _get('/api/ultron/tower', params)
    stats = (tower or {}).get('stats') or {}
    return {
        'ok': True,
        'city_key': key or 'all',
        'city_label': label,
        'total_jobs': int(stats.get('total_jobs') or 0),
        'jobs_today': int(stats.get('jobs_today') or 0),
        'companies': int(stats.get('companies') or 0),
    }


def _job_index(city: str = '', limit: int = 300) -> list[dict]:
    key, _ = _resolve_city(city) if city else (None, '')
    if key == '__unknown__':
        return []
    params: dict[str, Any] = {'limit': limit}
    if key:
        params['city'] = key
    jobs = _get('/api/jobs', params)
    return jobs if isinstance(jobs, list) else []


def _norm(s: str) -> str:
    return re.sub(r'\s+', ' ', (s or '').strip().lower())


def validate_kpi(payload: dict, city: str = '') -> dict:
    truth = _tower_stats(city)
    if not truth.get('ok'):
        return {'approved': False, 'errors': [truth.get('error') or 'tower fetch failed'], 'truth': truth}
    errors = []
    hero = str(payload.get('hero') or '').strip()
    m = re.search(r'-?\d+', hero.replace(',', ''))
    hero_n = int(m.group()) if m else None
    label = _norm(str(payload.get('hero_label') or ''))
    expect = None
    if 'today' in label or 'scraped today' in label:
        expect = truth['jobs_today']
    elif 'compan' in label:
        expect = truth['companies']
    elif 'total' in label or 'in city' in label or 'in this city' in label:
        expect = truth['total_jobs']
    else:
        expect = truth['jobs_today'] if city else truth['jobs_today']
    if hero_n is None:
        errors.append(f'hero has no number: {hero!r}')
    elif expect is not None and hero_n != expect:
        errors.append(
            f'hero {hero_n} != live {expect} '
            f'({truth["city_label"]} jobs_today={truth["jobs_today"]} '
            f'total={truth["total_jobs"]} companies={truth["companies"]})'
        )
    for line in payload.get('lines') or []:
        ls = str(line)
        lm = re.search(r'(\d[\d,]*)\s*$', ls.replace(',', ''))
        if not lm:
            continue
        n = int(lm.group(1).replace(',', ''))
        low = ls.lower()
        if 'total' in low and n != truth['total_jobs']:
            errors.append(f'line total {n} != {truth["total_jobs"]}')
        if 'compan' in low and n != truth['companies']:
            errors.append(f'line companies {n} != {truth["companies"]}')
    return {
        'approved': not errors,
        'errors': errors,
        'truth': truth,
        'kind': 'kpi',
    }


def validate_list(payload: dict, city: str = '') -> dict:
    rows = payload.get('rows') or []
    if not isinstance(rows, list) or not rows:
        return {'approved': False, 'errors': ['no rows'], 'kind': 'list'}
    jobs = _job_index(city)
    by_url = {_norm(j.get('job_url') or ''): j for j in jobs if j.get('job_url')}
    by_pair = {
        f"{_norm(j.get('title') or '')}|{_norm(j.get('company') or j.get('company_name') or '')}": j
        for j in jobs
    }
    errors = []
    seen_pairs: set[str] = set()
    for i, row in enumerate(rows):
        title = str(row.get('title') or '')
        co = str(row.get('company') or '')
        url = str(row.get('job_url') or row.get('url') or '').strip()
        pair = f'{_norm(title)}|{_norm(co)}'
        if pair in seen_pairs:
            errors.append(f'row {i+1} duplicate title+company: {title} @ {co}')
        seen_pairs.add(pair)
        if url:
            hit = by_url.get(_norm(url))
            if not hit:
                # still allow if pair matches (URL truncated on board)
                if pair not in by_pair:
                    errors.append(f'row {i+1} URL not in tower: {url[:60]}')
            else:
                if _norm(hit.get('title') or '') != _norm(title) and title:
                    # soft: title mismatch with URL
                    errors.append(
                        f'row {i+1} title mismatch for URL — '
                        f'board={title!r} tower={hit.get("title")!r}'
                    )
        else:
            if pair not in by_pair:
                errors.append(f'row {i+1} not found in tower: {title} @ {co}')
    return {
        'approved': not errors,
        'errors': errors,
        'kind': 'list',
        'checked_rows': len(rows),
        'tower_jobs_sampled': len(jobs),
    }


def validate_slices(payload: dict, city: str = '') -> dict:
    items = payload.get('items') or payload.get('slices') or []
    if not isinstance(items, list) or not items:
        return {'approved': False, 'errors': ['no slices'], 'kind': 'pie'}
    key, label = _resolve_city(city) if city else (None, 'All cities')
    if key == '__unknown__':
        return {'approved': False, 'errors': [f'unknown city {label}'], 'kind': 'pie'}
    params: dict[str, Any] = {'days': 0}
    if key:
        params['city'] = key
    sig = _get('/api/ultron/signals', params)
    signals = (sig.get('signals') or {}) if isinstance(sig, dict) else {}
    growing = signals.get('growing_roles') or []
    fastest = signals.get('fastest_companies') or []
    truth_map: dict[str, int] = {}
    for r in growing:
        name = _norm(r.get('name') or '')
        if name:
            truth_map[name] = int(
                r.get('recent') if r.get('recent') is not None else r.get('n') or 0
            )
    for c in fastest:
        name = _norm(c.get('name') or '')
        if name:
            truth_map[name] = int(
                c.get('recent') if c.get('recent') is not None else c.get('n') or 0
            )
    # Also allow per_role + top_companies from tower
    tower = _get('/api/ultron/tower', {'city': key} if key else {})
    for r in (tower.get('per_role') or []):
        name = _norm(r.get('name') or '')
        if name and name not in truth_map:
            truth_map[name] = int(r.get('n') or r.get('recent') or 0)
    for c in (tower.get('top_companies') or []):
        name = _norm(c.get('name') or '')
        if name and name not in truth_map:
            truth_map[name] = int(c.get('n') or c.get('recent') or 0)
    errors = []
    for it in items:
        if isinstance(it, dict):
            name = str(it.get('label') or it.get('name') or '')
            val = it.get('value', it.get('n', it.get('recent')))
        else:
            continue
        n = int(val)
        t = truth_map.get(_norm(name))
        if t is None:
            errors.append(f'label not in live signals/tower: {name}')
        elif t != n:
            errors.append(f'{name}: board={n} live={t}')
    return {
        'approved': not errors,
        'errors': errors,
        'kind': 'pie',
        'city_label': label,
        'truth_sample': dict(list(truth_map.items())[:8]),
    }


def validate_visual_prompt(payload: dict, city: str = '') -> dict:
    """Block prompts that embed numbers not present in live tower stats."""
    prompt = str(payload.get('prompt') or '')
    truth = _tower_stats(city)
    nums = [int(x.replace(',', '')) for x in re.findall(r'\b\d{1,6}\b', prompt)]
    # Allow small decoration numbers 1-12; flag big KPI-like numbers
    live = set()
    if truth.get('ok'):
        live.update({truth['total_jobs'], truth['jobs_today'], truth['companies']})
    errors = []
    for n in nums:
        if n < 13:
            continue
        if live and n not in live:
            # also allow numbers that appear in city job counts from roles — skip soft
            errors.append(
                f'prompt contains number {n} not in live KPIs '
                f'(today={truth.get("jobs_today")}, total={truth.get("total_jobs")}, '
                f'companies={truth.get("companies")}). Use a fact board for numbers.'
            )
    # Cap error noise
    errors = errors[:5]
    return {
        'approved': not errors,
        'errors': errors,
        'kind': 'visual_prompt',
        'truth': truth if truth.get('ok') else {},
        'advice': 'Prefer lens_send_*_board for any count/list; Nano Banana for mood only.',
    }


def run_validator(kind: str, payload_json: str, city: str = '') -> dict:
    try:
        payload = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
    except Exception as e:
        return {'approved': False, 'errors': [f'bad json: {e}'], 'kind': kind}
    if not isinstance(payload, dict):
        return {'approved': False, 'errors': ['payload must be object'], 'kind': kind}
    kind_l = (kind or '').strip().lower()
    if kind_l == 'kpi':
        result = validate_kpi(payload, city)
    elif kind_l == 'list':
        result = validate_list(payload, city)
    elif kind_l in {'pie', 'bar', 'slices'}:
        result = validate_slices(payload, city)
    elif kind_l in {'visual', 'visual_prompt', 'prompt'}:
        result = validate_visual_prompt(payload, city)
    else:
        result = {'approved': False, 'errors': [f'unknown kind {kind}'], 'kind': kind}
    tr = current_trace()
    if tr:
        tr.node('validator', validate_kind=kind_l, city=city, result=result)
        if not result.get('approved'):
            tr.hint(f'VALIDATOR rejected {kind_l}: {"; ".join(result.get("errors") or [])[:300]}')
    return result


@function_tool
def validator_approve(
    kind: str,
    payload_json: str,
    city: str = '',
    round: int = 1,
) -> str:
    """VALIDATOR role: approve data BEFORE any image/board generation.
    kind: kpi | list | pie | bar | visual_prompt
    payload_json examples:
      kpi: {"hero":"61","hero_label":"jobs scraped today in this city","lines":["Total in city · 74","Companies · 51"]}
      list: {"rows":[{"title":"...","company":"...","job_url":"..."}]}
      pie/bar: {"items":[{"label":"Role","value":24}]}
      visual_prompt: {"prompt":"...full image prompt..."}
    city: bangalore/bengaluru/… when scoped.
    On approved=false: call courier_ack, re-fetch STAGEHAND, fix payload, call validator again
    (max ~4 rounds). NEVER send image until approved=true."""
    result = run_validator(kind, payload_json, city)
    result['round'] = round
    result['max_rounds'] = MAX_VALIDATOR_ROUNDS
    if not result.get('approved'):
        if round >= MAX_VALIDATOR_ROUNDS:
            result['give_up'] = True
            result['advice'] = 'Max validator rounds — courier_ack apology and stop inventing.'
        else:
            result['advice'] = (
                'Rejected. courier_ack("Still verifying live facts…"), '
                're-call STAGEHAND, fix payload, validator_approve again.'
            )
    else:
        result['advice'] = 'Approved — you may now call the matching lens_send_* / lens_render tool.'
    return json.dumps(result, ensure_ascii=False)
