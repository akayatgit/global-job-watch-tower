"""Telegram guest access — lets Ashok grant/revoke temporary bot access from
his phone (`/allow`, `/revoke`, `/guests`) with zero ThinkPad terminal access.

Why this exists (2026-08-04 investor-demo incident, see documents/kanban.md
card #1 and documents/hermes-agent-integration.md): Hermes' own Telegram
connector enforces `TELEGRAM_ALLOWED_USERS` *before* any plugin hook runs, so
a blocked sender's messages never reach our code at all. The fix is to flip
Hermes to `TELEGRAM_ALLOW_ALL_USERS=true` (one-time manual step on the
ThinkPad) so every message reaches
`job_engine/hermes_plugins/vigil-image-only/__init__.py`, and enforce our
*own* allowlist there instead — fully controllable from this repo / Telegram.

Zero external dependencies (stdlib only) so it stays importable from
whatever Python environment the Hermes gateway happens to run under.

Store: job_engine/.data/telegram_guests.json (gitignored, ThinkPad-local).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # job_engine/
GUESTS_FILE = BASE_DIR / '.data' / 'telegram_guests.json'
HERMES_ENV = Path.home() / '.hermes' / '.env'

DEFAULT_TTL_MINUTES = 60.0
MAX_TTL_MINUTES = 60.0 * 24 * 14  # two weeks cap — a forgotten guest can't linger forever


def _load_hermes_env() -> dict:
    out: dict = {}
    if not HERMES_ENV.exists():
        return out
    for ln in HERMES_ENV.read_text(encoding='utf-8').splitlines():
        if not ln or ln.lstrip().startswith('#') or '=' not in ln:
            continue
        k, v = ln.split('=', 1)
        out[k.strip()] = v.strip()
    return out


def owner_ids() -> set:
    """Ashok's own id(s) — always allowed, never expire, can't be revoked."""
    env = _load_hermes_env()
    ids: set = set()
    for key in ('TELEGRAM_ALLOWED_USERS', 'TELEGRAM_HOME_CHANNEL'):
        raw = env.get(key, '')
        for part in raw.split(','):
            part = part.strip()
            if part:
                ids.add(part)
    return ids


def _load() -> dict:
    if not GUESTS_FILE.is_file():
        return {'guests': {}}
    try:
        data = json.loads(GUESTS_FILE.read_text(encoding='utf-8'))
        if not isinstance(data.get('guests'), dict):
            data['guests'] = {}
        return data
    except Exception:
        return {'guests': {}}


def _save(data: dict) -> None:
    GUESTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = GUESTS_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    tmp.replace(GUESTS_FILE)


def _prune(data: dict) -> bool:
    now = time.time()
    guests = data.get('guests', {})
    expired = [uid for uid, g in guests.items() if g.get('expires_at', 0) <= now]
    for uid in expired:
        guests.pop(uid, None)
    return bool(expired)


def is_allowed(user_id) -> bool:
    """True for the owner, or a guest whose grant hasn't expired yet."""
    user_id = str(user_id)
    if user_id in owner_ids():
        return True
    data = _load()
    if _prune(data):
        _save(data)
    g = data['guests'].get(user_id)
    return bool(g) and g.get('expires_at', 0) > time.time()


def add_guest(user_id, minutes: float = DEFAULT_TTL_MINUTES, label: str = '', added_by: str = '') -> dict:
    user_id = str(user_id)
    try:
        minutes = float(minutes)
    except (TypeError, ValueError):
        minutes = DEFAULT_TTL_MINUTES
    minutes = max(1.0, min(minutes, MAX_TTL_MINUTES))
    data = _load()
    _prune(data)
    now = time.time()
    entry = {
        'added_at': now,
        'expires_at': now + minutes * 60,
        'minutes': minutes,
        'label': (label or '').strip()[:80],
        'added_by': str(added_by or ''),
    }
    data['guests'][user_id] = entry
    _save(data)
    return entry


def revoke_guest(user_id) -> bool:
    user_id = str(user_id)
    data = _load()
    existed = data['guests'].pop(user_id, None) is not None
    if existed:
        _save(data)
    return existed


def list_guests() -> list:
    """Active (non-expired) guests, soonest-to-expire first."""
    data = _load()
    if _prune(data):
        _save(data)
    now = time.time()
    out = []
    for uid, g in data['guests'].items():
        out.append({
            'user_id': uid,
            'label': g.get('label') or '',
            'added_by': g.get('added_by') or '',
            'expires_in_s': max(0.0, g.get('expires_at', 0) - now),
            'expires_at': g.get('expires_at'),
        })
    out.sort(key=lambda g: g['expires_in_s'])
    return out


def format_ttl(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, _ = divmod(rem, 60)
    if h:
        return f'{h}h {m}m'
    return f'{m}m'
