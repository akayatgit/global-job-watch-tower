"""COURIER → DIRECTOR entrypoint (Hermes plugin calls this)."""

from __future__ import annotations

import argparse
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


def main(argv: list[str] | None = None) -> int:
    from app import config
    from app.director.agent import run_director
    from app.director.sessions import clear_session
    from app.director.tools_lens import send_simple_frame
    from app.prompt_dictionary import fill_cinematic

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
        prompt = fill_cinematic(
            setting=(
                'a bright Tamil Nadu morning comic-panel of a clean white courtyard '
                'with a jasmine creeper and soft Chennai daylight'
            ),
            environment=(
                'Pinterest 2026 editorial comic layout, empty chalkboard wiped clean, '
                'hopeful pause before a new skit begins'
            ),
            lighting='Soft high-key daylight, cream whites, warm sun accents',
            subjects=(
                'A young graduate in light clothes smiles gently, holding a blank notebook — '
                'ready for a fresh story'
            ),
            action='They take a calm breath; the skit resets with quiet energy',
            overlay_text='Fresh skit · let’s begin',
            template_key='tn_pinterest_comic_2026',
        )
        ok = send_simple_frame('Fresh skit · let’s begin', 'DIRECTOR memory cleared', prompt)
        print('SESSION_CLEARED' if ok else 'CLEAR_SEND_FAILED')
        return 0 if ok else 1

    if not config.OPENAI_API_KEY:
        print('OPENAI_API_KEY missing', file=sys.stderr)
        return 1

    from app.director.tools_lens import LAST_SEND
    from datetime import datetime, timezone

    before = LAST_SEND.stat().st_mtime if LAST_SEND.exists() else 0.0
    try:
        out = run_director(text, bot=bot, chat_id=chat)
    except Exception as e:
        print(f'DIRECTOR failed: {e}', file=sys.stderr)
        out = ''
        # fall through to rescue frame

    after = LAST_SEND.stat().st_mtime if LAST_SEND.exists() else 0.0
    if after <= before:
        # DIRECTOR talked but didn't deliver — rescue one frame
        from app.director.tools_stagehand import _get
        try:
            tower = _get('/api/ultron/tower')
            stats = (tower or {}).get('stats') or {}
            pulse = f"{stats.get('jobs_today', '—')} openings today"
        except Exception:
            pulse = 'Tower pulse loading'
        prompt = fill_cinematic(
            setting='a bright Tamil Nadu comic skit panel in a sunlit Chennai tech café',
            environment='Pinterest 2026 layout, filter coffee, soft comic energy, hopeful',
            lighting='High-key soft daylight',
            subjects='A graduate character leans in with a curious smile',
            action='They ask the next beat of the job-market skit',
            overlay_text=f'Vigil here · {pulse}'[:90],
            template_key='tn_pinterest_comic_2026',
        )
        ok = send_simple_frame('Vigil is listening', pulse, prompt)
        print('RESCUE_FRAME' if ok else 'RESCUE_FAILED')
        return 0 if ok else 1

    print(out or 'OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
