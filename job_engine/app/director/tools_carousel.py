"""CAROUSEL WORKSHOP — multi-slide album from live STAGEHAND data."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from agents import function_tool

from app import config


def _hermes_env() -> dict[str, str]:
    env_path = Path.home() / '.hermes' / '.env'
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    for ln in env_path.read_text(encoding='utf-8').splitlines():
        if not ln or ln.lstrip().startswith('#') or '=' not in ln:
            continue
        k, v = ln.split('=', 1)
        out[k.strip()] = v.strip()
    return out


@function_tool
def run_carousel(topic: str = '', role: str = '', city: str = '') -> str:
    """CAROUSEL WORKSHOP: Build a professional multi-slide TECH JOB MARKET MOVEMENT album
    from live tower data and send it via Telegram sendMediaGroup.
    Pass topic like 'Data Analyst in Bangalore' and/or role+city. Use when user says Carousel."""
    env = _hermes_env()
    token = env.get('TELEGRAM_BOT_TOKEN')
    chat = env.get('TELEGRAM_HOME_CHANNEL')
    if not token or not chat:
        return json.dumps({'ok': False, 'error': 'telegram_not_linked'})

    bits = [topic.strip(), role.strip(), city.strip()]
    topic_msg = 'Carousel ' + ' '.join(b for b in bits if b)
    if city and 'bangalore' in city.lower():
        topic_msg += ' Bengaluru'

    sys.path.insert(0, str(config.BASE_DIR))
    from app.carousel_gen import generate_carousel  # noqa: WPS433
    sys.path.insert(0, str(config.BASE_DIR / 'scripts'))
    from telegram_watch_tower import send_media_group  # noqa: WPS433

    try:
        paths, caption, run_dir = generate_carousel(topic_msg=topic_msg)
    except Exception as e:
        return json.dumps({'ok': False, 'error': str(e)[:300]})

    ok = send_media_group(token, chat, paths, caption)
    shutil.rmtree(run_dir, ignore_errors=True)
    return json.dumps({
        'ok': ok,
        'slides': len(paths) if ok else 0,
        'topic': topic_msg,
    })
