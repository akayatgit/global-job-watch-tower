"""LENS fact boards — Pillow charts/lists from exact STAGEHAND numbers (no Grok freehand)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agents import function_tool

from app import config
from app.director.fact_boards import (
    render_bar_board,
    render_kpi_board,
    render_list_board,
    render_pie_board,
)
from app.director.tools_lens import LAST_PROMPT, LAST_SEND, TMP, _hermes_env

TZ = ZoneInfo('Asia/Kolkata')


def _send_image(img, *, meta: str) -> bool:
    env = _hermes_env()
    token = env.get('TELEGRAM_BOT_TOKEN')
    chat = env.get('TELEGRAM_HOME_CHANNEL')
    if not token or not chat:
        return False
    TMP.mkdir(parents=True, exist_ok=True)
    LAST_PROMPT.write_text(f'FACT_BOARD {meta}', encoding='utf-8')
    path = TMP / f"board-{datetime.now(TZ).strftime('%H%M%S')}.png"
    img.save(path, format='PNG', optimize=True)
    import sys
    sys.path.insert(0, str(config.BASE_DIR / 'scripts'))
    from telegram_watch_tower import send_photo  # noqa: WPS433
    ok = send_photo(token, chat, path, caption='')
    path.unlink(missing_ok=True)
    if ok:
        LAST_SEND.write_text(
            json.dumps({
                'ts': datetime.now(TZ).isoformat(),
                'ok': True,
                'kind': 'fact_board',
                'meta': meta[:200],
            }),
            encoding='utf-8',
        )
    return ok


def _require_approval(kind: str, payload: dict, city: str = '') -> dict | None:
    """Hard gate — returns error dict if rejected, else None."""
    from app.director.tools_validator import run_validator, send_telegram_text
    result = run_validator(kind, json.dumps(payload), city)
    if result.get('approved'):
        return None
    errs = '; '.join(result.get('errors') or ['unknown'])[:180]
    send_telegram_text(f'Still verifying live facts… ({errs})')
    return result


def _parse_slices(items_json: str) -> list[tuple[str, int]]:
    data = json.loads(items_json) if isinstance(items_json, str) else items_json
    if not isinstance(data, list):
        raise ValueError('items_json must be a JSON list')
    out: list[tuple[str, int]] = []
    for row in data:
        if isinstance(row, dict):
            label = str(row.get('label') or row.get('name') or '').strip()
            val = row.get('value', row.get('n', row.get('recent')))
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            label, val = str(row[0]), row[1]
        else:
            continue
        if not label:
            continue
        out.append((label, int(val)))
    return out


@function_tool
def lens_send_kpi_board(
    title: str,
    hero: str,
    hero_label: str,
    lines_json: str = '[]',
    footer: str = '',
    city: str = '',
) -> str:
    """Send a KPI fact board drawn from EXACT numbers (Pillow). Use for city totals.
    lines_json: JSON list of short strings. Never invent hero — copy STAGEHAND values.
    Pass city when scoped. VALIDATOR auto-checks before send."""
    try:
        lines = json.loads(lines_json) if lines_json else []
        if not isinstance(lines, list):
            lines = []
        payload = {
            'hero': str(hero),
            'hero_label': hero_label,
            'lines': [str(x) for x in lines][:8],
        }
        rejected = _require_approval('kpi', payload, city)
        if rejected:
            return json.dumps({'ok': False, 'validator': rejected, 'blocked': True})
        img = render_kpi_board(
            title=title,
            hero=str(hero),
            hero_label=hero_label,
            lines=payload['lines'],
            footer=footer,
        )
        ok = _send_image(img, meta=f'kpi:{title}:{hero}')
        return json.dumps({'ok': ok, 'kind': 'kpi_board', 'validated': True})
    except Exception as e:
        return json.dumps({'ok': False, 'error': str(e)[:240]})


@function_tool
def lens_send_pie_board(
    title: str,
    items_json: str,
    subtitle: str = '',
    footer: str = '',
    city: str = '',
) -> str:
    """Send a pie chart + legend from EXACT items_json (Pillow — not freehand).
    items_json: [{"label":"Role","value":64}, ...] from STAGEHAND only.
    VALIDATOR auto-checks before send."""
    try:
        slices = _parse_slices(items_json)
        if not slices:
            return json.dumps({'ok': False, 'error': 'no_slices'})
        payload = {'items': [{'label': a, 'value': b} for a, b in slices]}
        rejected = _require_approval('pie', payload, city)
        if rejected:
            return json.dumps({'ok': False, 'validator': rejected, 'blocked': True})
        img = render_pie_board(
            title=title, slices=slices, subtitle=subtitle, footer=footer,
        )
        ok = _send_image(img, meta=f'pie:{title}:{slices[:5]}')
        return json.dumps({'ok': ok, 'kind': 'pie_board', 'slices': len(slices), 'validated': True})
    except Exception as e:
        return json.dumps({'ok': False, 'error': str(e)[:240]})


@function_tool
def lens_send_bar_board(
    title: str,
    items_json: str,
    subtitle: str = '',
    footer: str = '',
    city: str = '',
) -> str:
    """Send a bar chart from EXACT items_json (Pillow). VALIDATOR auto-checks before send."""
    try:
        bars = _parse_slices(items_json)
        if not bars:
            return json.dumps({'ok': False, 'error': 'no_bars'})
        payload = {'items': [{'label': a, 'value': b} for a, b in bars]}
        rejected = _require_approval('bar', payload, city)
        if rejected:
            return json.dumps({'ok': False, 'validator': rejected, 'blocked': True})
        img = render_bar_board(
            title=title, bars=bars, subtitle=subtitle, footer=footer,
        )
        ok = _send_image(img, meta=f'bar:{title}:{bars[:5]}')
        return json.dumps({'ok': ok, 'kind': 'bar_board', 'bars': len(bars), 'validated': True})
    except Exception as e:
        return json.dumps({'ok': False, 'error': str(e)[:240]})


@function_tool
def lens_send_list_board(
    title: str,
    rows_json: str,
    subtitle: str = '',
    footer: str = '',
    city: str = '',
) -> str:
    """Send a text stat board from EXACT job rows (Pillow).
    rows_json: [{"title":"...","company":"...","posted_date":"...","job_url":"..."}, ...]
    Include job_url when Ashok asks for links. VALIDATOR auto-checks before send."""
    try:
        rows = json.loads(rows_json) if rows_json else []
        if not isinstance(rows, list) or not rows:
            return json.dumps({'ok': False, 'error': 'no_rows'})
        rejected = _require_approval('list', {'rows': rows}, city)
        if rejected:
            return json.dumps({'ok': False, 'validator': rejected, 'blocked': True})
        img = render_list_board(
            title=title, rows=rows, subtitle=subtitle, footer=footer,
        )
        ok = _send_image(img, meta=f'list:{title}:{len(rows)}')
        return json.dumps({'ok': ok, 'kind': 'list_board', 'rows': len(rows), 'validated': True})
    except Exception as e:
        return json.dumps({'ok': False, 'error': str(e)[:240]})
