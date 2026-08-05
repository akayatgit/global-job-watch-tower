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

**Username access (2026-08-04):** onboarding a guest by numeric id needs a
detour through @userinfobot. When Ashok already knows someone's `@handle`
(e.g. "allow telegram username @azr0099"), grant it directly — no id lookup
needed. `DEFAULT_ALLOWED_USERNAMES` below is a code-reviewed, git-tracked
permanent allowlist (never expires, ships on deploy — unlike numeric guests
which live in the gitignored, ThinkPad-local JSON store). `/allowuser` /
`/revokeuser` manage additional handles from Telegram without a code change,
stored the same way as numeric guests. Matching is done against whatever
username the incoming Telegram update carries for the sender — see
`_sender_username()` in the plugin for the (best-effort, defensive) lookup.
"""

from __future__ import annotations

import fcntl
import functools
import json
import math
import threading
import time
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # job_engine/
GUESTS_FILE = BASE_DIR / '.data' / 'telegram_guests.json'
HERMES_ENV = Path.home() / '.hermes' / '.env'
STORE_THREAD_LOCK = threading.RLock()

DEFAULT_TTL_MINUTES = 60.0
MAX_TTL_MINUTES = 60.0 * 24 * 14  # two weeks cap — a forgotten guest can't linger forever

# Permanent, code-reviewed username allowlist — never expires, no ThinkPad
# manual step, effective as soon as this deploys. Add a handle here when
# Ashok says "allow telegram username @whoever"; usernames are matched
# case-insensitively with or without the leading "@".
DEFAULT_ALLOWED_USERNAMES = {
    'azr0099',
    'supriyamk',  # Ashok's wife (2026-08-04)
}


class GuestStoreError(RuntimeError):
    """Access decisions must fail closed when persisted state is unreadable."""


@contextmanager
def _store_lock():
    """Serialize read-modify-write across threads and local processes."""
    with STORE_THREAD_LOCK:
        GUESTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        lock_path = GUESTS_FILE.with_suffix('.lock')
        with lock_path.open('a+', encoding='utf-8') as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _locked(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with _store_lock():
            return func(*args, **kwargs)

    return wrapper


def _norm_username(username) -> str:
    return str(username or '').strip().lstrip('@').lower()


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
        return {
            'guests': {},
            'usernames': {},
            'blocked_ids': {},
            'blocked_usernames': {},
        }
    try:
        data = json.loads(GUESTS_FILE.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('guest store root must be an object')
        for key in ('guests', 'usernames', 'blocked_ids', 'blocked_usernames'):
            if key not in data:
                data[key] = {}
            elif not isinstance(data[key], dict):
                raise ValueError(f'guest store field {key} must be an object')
        return data
    except Exception as exc:
        raise GuestStoreError('Telegram guest access store is unreadable') from exc


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


@_locked
def is_allowed(user_id, username=None) -> bool:
    """True for the owner, a guest whose grant hasn't expired, or a sender
    whose Telegram @username is on the allowlist (default or granted)."""
    user_id = str(user_id)
    if user_id in owner_ids():
        return True
    data = _load()
    if user_id in data['blocked_ids']:
        return False
    handle = _norm_username(username)
    if handle and handle in data['blocked_usernames']:
        return False
    if handle and (
        handle in DEFAULT_ALLOWED_USERNAMES
        or handle in data['usernames']
    ):
        return True
    if _prune(data):
        _save(data)
    g = data['guests'].get(user_id)
    return bool(g) and g.get('expires_at', 0) > time.time()


@_locked
def is_username_allowed(username) -> bool:
    """True for a hardcoded default handle or one granted via /allowuser."""
    handle = _norm_username(username)
    if not handle:
        return False
    data = _load()
    if handle in data['blocked_usernames']:
        return False
    if handle in DEFAULT_ALLOWED_USERNAMES:
        return True
    return handle in data['usernames']


@_locked
def add_guest(user_id, minutes: float = DEFAULT_TTL_MINUTES, label: str = '', added_by: str = '') -> dict:
    user_id = str(user_id)
    try:
        minutes = float(minutes)
    except (TypeError, ValueError) as exc:
        raise ValueError('minutes must be a number') from exc
    if not math.isfinite(minutes) or minutes < 1 or minutes > MAX_TTL_MINUTES:
        raise ValueError(f'minutes must be between 1 and {int(MAX_TTL_MINUTES)}')
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
    data['blocked_ids'].pop(user_id, None)
    data['guests'][user_id] = entry
    _save(data)
    return entry


@_locked
def revoke_guest(user_id) -> bool:
    user_id = str(user_id)
    data = _load()
    existed = data['guests'].pop(user_id, None) is not None
    if existed:
        _save(data)
    return existed


@_locked
def add_username(username, added_by: str = '') -> dict:
    """Grant permanent access to a Telegram @username (no expiry — matches
    the code-reviewed defaults; use /revokeuser to undo)."""
    handle = _norm_username(username)
    data = _load()
    entry = {'added_at': time.time(), 'added_by': str(added_by or '')}
    data['blocked_usernames'].pop(handle, None)
    data['usernames'][handle] = entry
    _save(data)
    return entry


@_locked
def revoke_username(username) -> bool:
    """Remove a granted @username. Handles baked into DEFAULT_ALLOWED_USERNAMES
    can't be revoked this way by design — that's a code change, not a runtime one."""
    handle = _norm_username(username)
    if handle in DEFAULT_ALLOWED_USERNAMES:
        return False
    data = _load()
    existed = data['usernames'].pop(handle, None) is not None
    if existed:
        _save(data)
    return existed


@_locked
def block_guest(user_id, blocked_by: str = '') -> dict:
    """Deny a numeric Telegram id until Ashok explicitly allows it again."""
    user_id = str(user_id).strip()
    data = _load()
    data['guests'].pop(user_id, None)
    entry = {'blocked_at': time.time(), 'blocked_by': str(blocked_by or '')}
    data['blocked_ids'][user_id] = entry
    _save(data)
    return entry


@_locked
def block_username(username, blocked_by: str = '') -> dict:
    """Deny a Telegram username, including a code-tracked default."""
    handle = _norm_username(username)
    data = _load()
    data['usernames'].pop(handle, None)
    entry = {'blocked_at': time.time(), 'blocked_by': str(blocked_by or '')}
    data['blocked_usernames'][handle] = entry
    _save(data)
    return entry


@_locked
def list_usernames() -> list:
    """Every allowed @username — permanent defaults first, then granted ones."""
    data = _load()
    out = [
        {'username': h, 'source': 'default', 'added_by': '', 'added_at': None}
        for h in sorted(DEFAULT_ALLOWED_USERNAMES)
        if h not in data['blocked_usernames']
    ]
    for h, g in data['usernames'].items():
        if h in DEFAULT_ALLOWED_USERNAMES:
            continue
        out.append({
            'username': h,
            'source': 'granted',
            'added_by': g.get('added_by') or '',
            'added_at': g.get('added_at'),
        })
    return out


@_locked
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


@_locked
def list_blocked() -> dict[str, list[str]]:
    data = _load()
    return {
        'user_ids': sorted(data['blocked_ids']),
        'usernames': sorted(data['blocked_usernames']),
    }


def format_ttl(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, _ = divmod(rem, 60)
    if h:
        return f'{h}h {m}m'
    return f'{m}m'
