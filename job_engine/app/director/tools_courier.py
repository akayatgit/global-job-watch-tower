"""COURIER — Telegram text delivery for chat / summarize / wait acks."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agents import function_tool

from app import config
from app.director.trace import current_trace

TZ = ZoneInfo('Asia/Kolkata')
TMP = config.BASE_DIR / '.data' / 'director_frames'
LAST_TEXT_SEND = TMP / 'last_text_send.json'


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


def send_telegram_text(
    text: str,
    *,
    max_len: int = 350,
    kind: str = 'courier_ack',
) -> bool:
    """Send Telegram text. kind=courier_reply marks a successful chat delivery."""
    env = _hermes_env()
    token = env.get('TELEGRAM_BOT_TOKEN')
    # Sender's chat when set by the router (guest support) — home channel otherwise
    chat = os.getenv('DIRECTOR_TARGET_CHAT') or env.get('TELEGRAM_HOME_CHANNEL')
    if not token or not chat:
        return False
    msg = (text or '').strip()[:max_len]
    if not msg:
        return False
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    body = urllib.parse.urlencode({
        'chat_id': chat,
        'text': msg,
        'disable_web_page_preview': 'true',
    }).encode()
    req = urllib.request.Request(
        url, data=body, headers={'Content-Type': 'application/x-www-form-urlencoded'},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        ok = bool(data.get('ok'))
    except Exception:
        ok = False
    tr = current_trace()
    if tr:
        tr.node(kind, text=msg[:500], ok=ok, chars=len(msg))
    if ok and kind == 'courier_reply':
        TMP.mkdir(parents=True, exist_ok=True)
        LAST_TEXT_SEND.write_text(
            json.dumps({
                'ts': datetime.now(TZ).isoformat(),
                'ok': True,
                'chars': len(msg),
                'preview': msg[:200],
            }),
            encoding='utf-8',
        )
    return ok


@function_tool
def courier_ack(message: str = 'Checking live tower facts… hang tight.') -> str:
    """Short wait signal while STAGEHAND / VALIDATOR work. Keep under ~120 chars."""
    ok = send_telegram_text(message, max_len=350, kind='courier_ack')
    return json.dumps({'ok': ok, 'acked': (message or '')[:120]})


@function_tool
def courier_reply(message: str) -> str:
    """Send Ashok a normal Telegram text reply (chat / summarize). Use this for ALL answers
    in text mode. Never invent numbers — STAGEHAND first. Max ~3900 chars; keep punchy."""
    msg = (message or '').strip()
    if not msg:
        return json.dumps({'ok': False, 'error': 'empty'})
    ok = send_telegram_text(msg, max_len=3900, kind='courier_reply')
    return json.dumps({'ok': ok, 'chars': len(msg[:3900])})
