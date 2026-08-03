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


def _mtime() -> float:
    from app.director.tools_lens import LAST_SEND
    return LAST_SEND.stat().st_mtime if LAST_SEND.exists() else 0.0


def _answer_fallback(text: str) -> bool:
    """Last resort: answer the asked question with live facts — never generic Still here."""
    from app.director.tools_lens import send_image_bytes_prompt
    from app.director.tools_stagehand import _get
    from app.prompt_dictionary import assert_visual_prompt

    if _looks_like_heat(text):
        data = _get('/api/ultron/health')
        v = (data or {}).get('vitals') or {}
        c = v.get('heat_c')
        label = v.get('heat_label') or '—'
        detail = (v.get('heat_detail') or '')[:40]
        deg = f'{round(c)}°C' if isinstance(c, (int, float)) else '—'
        prompt = (
            f'Hyper-clean 2D vector illustration, square phone glance. Dark graphite stage with a '
            f'vertical matte-black heat gauge; warm orange fill rising to show {deg}. '
            f'Subtle faint grid, one ember accent spark, high contrast, generous negative space, '
            f'no photorealism, no frosted cards, no atrium, no India hologram, no PowerPoint chrome. '
            f'Draw bold dual-weight sans typography into the art: hero "Tower heat"; '
            f'fact crumb "{deg} · {label}". Tiny detail type allowed: "{detail}". '
            f'Studio-clean lighting, sharp edges, asymmetric but balanced, readable as Telegram thumbnail. '
            f'Playful ops-buddy Jarvis energy — data-first status glance, not a campaign poster. '
            f'Expand composition: gauge left-of-center, type right, soft vignette, crisp iconography, '
            f'one geometric accent only, premium illustration finish, square 1:1.'
        )
        return send_image_bytes_prompt(assert_visual_prompt(prompt))

    if _looks_like_roles(text):
        sig = _get('/api/ultron/signals', {'days': 0})
        s = (sig or {}).get('signals') or {}
        growing = (s.get('growing_roles') or [])[:5]
        if not growing:
            tower = _get('/api/ultron/tower')
            growing = [
                {'name': r.get('name'), 'n': r.get('n') or r.get('recent') or 0}
                for r in ((tower or {}).get('per_role') or [])[:5]
            ]
        slices = []
        for r in growing[:5]:
            name = (r.get('name') or 'Role').strip()
            n = r.get('delta') if r.get('delta') is not None else r.get('n') or r.get('recent') or 0
            slices.append(f'{name} {int(n)}')
        if not slices:
            slices = ['No fresher pulse yet 0']
        legend = '; '.join(slices)
        prompt = (
            f'A clean modern pie chart graphic of top job roles for freshers in the last 24 hours. '
            f'Segments in distinct colors (bright blue, orange, green, purple, teal). Each slice '
            f'labeled with role name and count from live tower data: {legend}. Include a clear '
            f'legend matching those exact numbers. Minimal title text "Fresher roles · 24h". '
            f'High-contrast 2D vector, phone-readable, no frosted UI cards, no glass atrium, '
            f'no India hologram, no PowerPoint title bar clutter. Typography drawn into the chart. '
            f'Studio-clean lighting, sharp edges, generous negative space around the pie, one thin '
            f'geometric accent only. Biggest slice visually dominant. Square 1:1. Premium data '
            f'illustration — witty ops glance, not a marketing poster. Reference legend values '
            f'exactly; do not invent extra roles or change the counts. Add soft depth and crisp '
            f'edges so labels stay legible on a phone screen in Telegram.'
        )
        return send_image_bytes_prompt(assert_visual_prompt(prompt))

    tower = _get('/api/ultron/tower')
    stats = (tower or {}).get('stats') or {}
    today = stats.get('jobs_today', '—')
    total = stats.get('total_jobs', '—')
    prompt = (
        f'Hyper-clean 2D vector illustration, square. Midnight navy with a neon signal spike mark. '
        f'High contrast, playful, generous negative space, no frosted cards, no atrium, no hologram, '
        f'no PowerPoint. Draw typography into the art: hero "Tower pulse"; '
        f'fact crumb "{today} today · {total} live". Studio lighting, sharp edges, one cyan accent, '
        f'phone-readable Telegram glance, premium illustration finish, asymmetric balance, '
        f'data-first Jarvis status — expand with concrete depth, vignette, and icon placement detail '
        f'so the visual brief stays richly specific for an image model.'
    )
    return send_image_bytes_prompt(assert_visual_prompt(prompt))


def _attempt(text: str, bot: str, chat: str, *, attempt: int, before: float) -> bool:
    from app.director.agent import run_director

    try:
        out = run_director(text, bot=bot, chat_id=chat)
        sent = _mtime() > before
        _log('attempt_done', attempt=attempt, sent=sent, out=(out or '')[:80])
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
        print(f'DIRECTOR failed attempt={attempt}: {e}', file=sys.stderr)
        return False


def main(argv: list[str] | None = None) -> int:
    _bootstrap_secrets()
    from importlib import reload
    import app.config as cfg
    reload(cfg)

    from app.director.sessions import clear_session
    from app.director.tools_lens import send_simple_frame
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

    if len(key) < 20 or key.lower().startswith('ollama'):
        _log('bad_key', key_len=len(key), key_prefix=key[:12])
        print('OPENAI_API_KEY missing or poisoned — using answer fallback', file=sys.stderr)
        try:
            ok = _answer_fallback(text)
            print('ANSWER_FALLBACK' if ok else 'FALLBACK_FAILED')
            return 0 if ok else 1
        except Exception as e:
            print(f'fallback failed: {e}', file=sys.stderr)
            return 1

    before = _mtime()
    if _attempt(text, bot, chat, attempt=1, before=before):
        _log('success', attempt=1)
        return 0

    _log('retrying', reason='no_telegram_send_after_attempt_1')
    before2 = _mtime()
    if _attempt(text, bot, chat, attempt=2, before=before2):
        _log('success', attempt=2)
        return 0

    try:
        ok = _answer_fallback(text)
        _log('answer_fallback', ok=ok)
        print('ANSWER_FALLBACK' if ok else 'FALLBACK_FAILED')
        return 0 if ok else 1
    except Exception as e:
        _log('fallback_error', error=str(e)[:400])
        print(f'ANSWER_FALLBACK failed: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
