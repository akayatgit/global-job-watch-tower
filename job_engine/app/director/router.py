"""COURIER → DIRECTOR entrypoint (Hermes plugin calls this)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _default_chat() -> str:
    env_path = Path.home() / '.hermes' / '.env'
    if not env_path.exists():
        return ''
    for ln in env_path.read_text().splitlines():
        if ln.startswith('TELEGRAM_HOME_CHANNEL='):
            return ln.split('=', 1)[1].strip()
    return ''


def _looks_like_heat(text: str) -> bool:
    return bool(re.search(
        r'\b(heat|temp|temperature|warm|hot|cool(?:ing)?|cpu|gpu|thermal)\b',
        text or '',
        re.I,
    ))


def _rescue_fact(text: str) -> tuple[str, str, str]:
    """Return (punchline, fact_line, mood) from live APIs for rescue only."""
    from app.director.tools_stagehand import _get

    if _looks_like_heat(text):
        try:
            data = _get('/api/ultron/health')
            v = (data or {}).get('vitals') or {}
            c = v.get('heat_c')
            label = v.get('heat_label') or '—'
            detail = v.get('heat_detail') or ''
            deg = f'{round(c)}°C' if isinstance(c, (int, float)) else '—'
            return 'Tower heat', f'{deg} · {label}', 'heat'
        except Exception:
            return 'Tower heat', 'heat loading', 'heat'
    try:
        tower = _get('/api/ultron/tower')
        stats = (tower or {}).get('stats') or {}
        return 'Still here', f"{stats.get('jobs_today', '—')} openings today", 'rescue'
    except Exception:
        return 'Still here', 'Tower pulse loading', 'rescue'


def main(argv: list[str] | None = None) -> int:
    from app import config
    from app.director.agent import run_director
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

    if text.lower().strip() in {'/new', '/reset', '/clear', 'new', 'reset', 'clear'}:
        clear_session(bot, chat)
        prompt = fallback_graphic_prompt(
            punchline='Fresh thread',
            fact_line='Memory cleared',
            mood='reset',
        )
        ok = send_simple_frame('', '', prompt)
        print('SESSION_CLEARED' if ok else 'CLEAR_SEND_FAILED')
        return 0 if ok else 1

    if not config.OPENAI_API_KEY:
        print('OPENAI_API_KEY missing', file=sys.stderr)
        return 1

    from app.director.tools_lens import LAST_SEND

    before = LAST_SEND.stat().st_mtime if LAST_SEND.exists() else 0.0
    try:
        out = run_director(text, bot=bot, chat_id=chat)
    except Exception as e:
        print(f'DIRECTOR failed: {e}', file=sys.stderr)
        out = ''

    after = LAST_SEND.stat().st_mtime if LAST_SEND.exists() else 0.0
    if after <= before:
        punch, fact, mood = _rescue_fact(text)
        prompt = fallback_graphic_prompt(punchline=punch, fact_line=fact, mood=mood)
        ok = send_simple_frame('', '', prompt)
        print('RESCUE_FRAME' if ok else 'RESCUE_FAILED')
        return 0 if ok else 1

    print(out or 'OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
