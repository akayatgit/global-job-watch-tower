"""COURIER → DIRECTOR entrypoint (Hermes plugin calls this)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

TZ = ZoneInfo('Asia/Kolkata')
RUN_LOG = _ROOT / '.data' / 'director_frames' / 'director_runs.log'


def _bootstrap_secrets() -> None:
    """Force job_engine .env over any Hermes dummy OPENAI_API_KEY in parent env."""
    from dotenv import load_dotenv
    load_dotenv(_ROOT / '.env', override=True)
    for key in (
        'OPENAI_API_KEY', 'OPENAI_BRAIN_MODEL',
        'REPLICATE_API_TOKEN', 'REPLICATE_MODEL',
    ):
        val = os.getenv(key, '').strip()
        if val:
            os.environ[key] = val


def _default_chat() -> str:
    env_path = Path.home() / '.hermes' / '.env'
    if not env_path.exists():
        return ''
    for ln in env_path.read_text().splitlines():
        if ln.startswith('TELEGRAM_HOME_CHANNEL='):
            return ln.split('=', 1)[1].strip()
    return ''


def _log(event: str, **extra) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    row = {'ts': datetime.now(TZ).isoformat(), 'event': event, **extra}
    with RUN_LOG.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(f'DIRECTOR_LOG {event} {json.dumps(extra, ensure_ascii=False)[:400]}', file=sys.stderr)


def _looks_like_heat(text: str) -> bool:
    return bool(re.search(
        r'\b(heat|temp|temperature|warm|hot|cool(?:ing)?|cpu|gpu|thermal)\b',
        text or '',
        re.I,
    ))


def _looks_like_roles(text: str) -> bool:
    return bool(re.search(
        r'\b(role|roles|pie|chart|fresher|freshers|top jobs?|hiring)\b',
        text or '',
        re.I,
    ))


def _looks_like_ai(text: str) -> bool:
    return bool(re.search(r'\b(ai|ml|artificial|machine learning)\b', text or '', re.I))


def _city_from_text(text: str) -> str:
    from app.cities import normalize_city_filter
    low = (text or '').lower()
    for alias in (
        'bengaluru', 'bangalore', 'chennai', 'hyderabad', 'pune', 'mumbai',
        'delhi', 'gurugram', 'gurgaon', 'noida', 'kerala', 'remote',
    ):
        if re.search(rf'\b{re.escape(alias)}\b', low):
            return normalize_city_filter(alias) or alias
    return ''


def _mtime() -> float:
    from app.director.tools_lens import LAST_SEND
    return LAST_SEND.stat().st_mtime if LAST_SEND.exists() else 0.0


def _answer_fallback(text: str) -> bool:
    """Last resort: Pillow fact boards from live STAGEHAND — never Grok freehand numbers."""
    from app.director.fact_boards import (
        render_kpi_board, render_list_board, render_pie_board,
    )
    from app.director.tools_fact_board import _send_image
    from app.director.tools_stagehand import _get, _is_ai_title
    from app.cities import city_label

    if _looks_like_heat(text):
        data = _get('/api/ultron/health')
        v = (data or {}).get('vitals') or {}
        c = v.get('heat_c')
        label = v.get('heat_label') or '—'
        detail = (v.get('heat_detail') or '')[:48]
        deg = f'{round(c)}°C' if isinstance(c, (int, float)) else '—'
        img = render_kpi_board(
            title='Tower heat',
            hero=deg,
            hero_label=str(label),
            lines=[detail] if detail else [],
            footer='ThinkPad vitals · live',
        )
        return _send_image(img, meta=f'fallback_heat:{deg}')

    city = _city_from_text(text)

    if re.search(r'\b(fresh|latest|newest|catches?)\b', text or '', re.I):
        from app.cities import normalize_city_filter
        key = city or None
        params = {'limit': 80}
        if key:
            params['city'] = key
        jobs = _get('/api/jobs', params)
        rows = []
        seen = set()
        if isinstance(jobs, list):
            for j in jobs:
                title = (j.get('title') or '').strip()
                co = (j.get('company') or j.get('company_name') or '').strip()
                pair = f'{title.lower()}|{co.lower()}'
                if not title or pair in seen:
                    continue
                seen.add(pair)
                rows.append({
                    'title': title,
                    'company': co,
                    'posted_date': str(j.get('posted_date') or ''),
                    'job_url': j.get('job_url') or '',
                })
                if len(rows) >= 3:
                    break
        scope = city_label(city) if city else 'All India'
        img = render_list_board(
            title=f'Fresh catches · {scope}',
            rows=rows or [{'title': 'No fresh jobs yet', 'company': ''}],
            subtitle='Newest scrape · diversified · with links',
            footer='Pillow fact board · stagehand freshest',
        )
        return _send_image(img, meta=f'fallback_fresh:{scope}:{len(rows)}')

    if _looks_like_ai(text) and city:
        jobs = _get('/api/jobs', {'city': city, 'limit': 300})
        rows = []
        if isinstance(jobs, list):
            for j in jobs:
                if _is_ai_title(j.get('title') or ''):
                    rows.append({
                        'title': j.get('title'),
                        'company': j.get('company') or j.get('company_name'),
                        'posted_date': str(j.get('posted_date') or ''),
                    })
                if len(rows) >= 8:
                    break
        img = render_list_board(
            title=f'AI roles · {city_label(city)}',
            rows=rows or [{'title': 'No strict AI/ML titles in city yet', 'company': ''}],
            subtitle=f'{len(rows)} matched (Apprentice excluded)',
            footer='Tower facts · strict AI title match',
        )
        return _send_image(img, meta=f'fallback_ai:{city}:{len(rows)}')

    if city and re.search(r'\b(today|jobs?|total|how many|companies)\b', text or '', re.I):
        tower = _get('/api/ultron/tower', {'city': city})
        stats = (tower or {}).get('stats') or {}
        img = render_kpi_board(
            title=city_label(city),
            hero=str(stats.get('jobs_today', '—')),
            hero_label='jobs scraped today in this city',
            lines=[
                f"Total in city · {stats.get('total_jobs', '—')}",
                f"Companies · {stats.get('companies', '—')}",
            ],
            footer='City-scoped tower facts',
        )
        return _send_image(img, meta=f'fallback_city:{city}')

    if _looks_like_roles(text) or 'pie' in (text or '').lower():
        params = {'days': 0}
        if city:
            params['city'] = city
        sig = _get('/api/ultron/signals', params)
        s = (sig or {}).get('signals') or {}
        growing = (s.get('growing_roles') or [])[:6]
        slices = []
        for r in growing:
            name = (r.get('name') or 'Role').strip()
            n = r.get('recent') if r.get('recent') is not None else r.get('n') or 0
            slices.append((name, int(n)))
        scope = city_label(city) if city else 'All India'
        img = render_pie_board(
            title=f'Roles · {scope}',
            slices=slices or [('No pulse yet', 1)],
            subtitle='Live signal window · exact counts',
            footer='Pillow fact board · not freehand',
        )
        return _send_image(img, meta=f'fallback_pie:{scope}')

    tower = _get('/api/ultron/tower')
    stats = (tower or {}).get('stats') or {}
    img = render_kpi_board(
        title='Tower pulse',
        hero=str(stats.get('jobs_today', '—')),
        hero_label='jobs today · all India',
        lines=[f"Live index · {stats.get('total_jobs', '—')}"],
        footer='All-India scope',
    )
    return _send_image(img, meta='fallback_pulse')


def _attempt(
    text: str, bot: str, chat: str, *, attempt: int, before: float, trace,
) -> bool:
    from app.director.agent import run_director

    try:
        if trace:
            trace.node('attempt_begin', attempt=attempt)
        out = run_director(text, bot=bot, chat_id=chat, trace=trace, attempt=attempt)
        sent = _mtime() > before
        _log('attempt_done', attempt=attempt, sent=sent, out=(out or '')[:80])
        if trace:
            trace.node('attempt_result', attempt=attempt, sent=sent, final_output=out)
        if sent:
            print(out or 'OK')
        return sent
    except Exception as e:
        _log(
            'attempt_error',
            attempt=attempt,
            error=str(e)[:400],
            tb=traceback.format_exc()[-800:],
        )
        if trace:
            trace.node('attempt_error', attempt=attempt, error=str(e), tb=traceback.format_exc()[-1200:])
        print(f'DIRECTOR failed attempt={attempt}: {e}', file=sys.stderr)
        return False


def main(argv: list[str] | None = None) -> int:
    _bootstrap_secrets()
    from importlib import reload
    import app.config as cfg
    reload(cfg)

    from app.director.sessions import clear_session
    from app.director.tools_lens import send_simple_frame
    from app.director.trace import clear_current, start_trace
    from app.prompt_dictionary import fallback_graphic_prompt

    p = argparse.ArgumentParser(description='DIRECTOR router')
    p.add_argument('--bot', default='vigil_akay_bot')
    p.add_argument('--chat', default='')
    p.add_argument('--text', default='')
    p.add_argument('message', nargs='*', help='fallback positional message')
    args = p.parse_args(argv)

    text = (args.text or ' '.join(args.message)).strip()
    if not text and not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    if not text:
        print('DIRECTOR: empty message', file=sys.stderr)
        return 2

    bot = args.bot.strip().lstrip('@') or 'vigil_akay_bot'
    chat = args.chat.strip() or _default_chat()
    if not chat:
        print('DIRECTOR: missing --chat / TELEGRAM_HOME_CHANNEL', file=sys.stderr)
        return 2

    key = os.getenv('OPENAI_API_KEY', '')
    _log('start', bot=bot, chat=chat, text=text[:160], key_len=len(key), key_prefix=key[:7])

    if text.lower().strip() in {'/new', '/reset', '/clear', 'new', 'reset', 'clear'}:
        clear_session(bot, chat)
        prompt = fallback_graphic_prompt(
            punchline='Fresh thread',
            fact_line='Memory cleared',
            mood='reset',
        )
        ok = send_simple_frame('', '', prompt)
        _log('session_cleared', ok=ok)
        print('SESSION_CLEARED' if ok else 'CLEAR_SEND_FAILED')
        return 0 if ok else 1

    trace = start_trace(bot=bot, chat=chat, text=text)
    try:
        # Immediate ack so Ashok is never left silent while DIRECTOR/VALIDATOR work
        from app.director.tools_validator import send_telegram_text
        send_telegram_text('On it — pulling live tower facts…')

        if len(key) < 20 or key.lower().startswith('ollama'):
            _log('bad_key', key_len=len(key), key_prefix=key[:12])
            trace.hint('OPENAI key missing/poisoned — answer fallback path')
            print('OPENAI_API_KEY missing or poisoned — using answer fallback', file=sys.stderr)
            try:
                ok = _answer_fallback(text)
                trace.node('answer_fallback', ok=ok, reason='bad_key')
                trace.finish('fallback' if ok else 'failed', {'kind': 'answer_fallback', 'ok': ok})
                print('ANSWER_FALLBACK' if ok else 'FALLBACK_FAILED')
                return 0 if ok else 1
            except Exception as e:
                trace.finish('failed', {'error': str(e)})
                print(f'fallback failed: {e}', file=sys.stderr)
                return 1

        before = _mtime()
        if _attempt(text, bot, chat, attempt=1, before=before, trace=trace):
            _log('success', attempt=1)
            trace.finish('ok', {'kind': 'director', 'attempt': 1, 'trace_id': trace.id})
            print(f'TRACE:{trace.id}', file=sys.stderr)
            return 0

        _log('retrying', reason='no_telegram_send_after_attempt_1')
        trace.hint('Attempt 1 did not deliver a Telegram image — retrying')
        before2 = _mtime()
        if _attempt(text, bot, chat, attempt=2, before=before2, trace=trace):
            _log('success', attempt=2)
            trace.finish('ok_retry', {'kind': 'director', 'attempt': 2, 'trace_id': trace.id})
            print(f'TRACE:{trace.id}', file=sys.stderr)
            return 0

        try:
            ok = _answer_fallback(text)
            _log('answer_fallback', ok=ok)
            trace.node('answer_fallback', ok=ok, reason='both_attempts_missed_send')
            trace.hint('Both DIRECTOR attempts missed send — Pillow answer fallback used')
            trace.finish('fallback' if ok else 'failed', {'kind': 'answer_fallback', 'ok': ok})
            print('ANSWER_FALLBACK' if ok else 'FALLBACK_FAILED')
            print(f'TRACE:{trace.id}', file=sys.stderr)
            return 0 if ok else 1
        except Exception as e:
            _log('fallback_error', error=str(e)[:400])
            trace.finish('failed', {'error': str(e)})
            print(f'ANSWER_FALLBACK failed: {e}', file=sys.stderr)
            return 1
    finally:
        clear_current()


if __name__ == '__main__':
    raise SystemExit(main())
