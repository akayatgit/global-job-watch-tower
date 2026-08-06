"""JobMaster waitlist — emails collected from guests whose experience band
(1-4 / 5-10 / 10+ years) is outside the current GTM focus (Intern, Fresher).

Ashok's instruction (2026-08-06): "We are going to GTM with only freshers
and interns as focused group of guests... for other than intern and
fresher, a static message, experienced jobs are coming soon, please
provide your emailid, we will let you know."

Store: job_engine/.data/telegram_waitlist.json (gitignored, ThinkPad-local —
same convention as telegram_guests.py). Read via the /waitlist owner
command in telegram_job_bot.py so this list is never a write-only black
hole — Ashok can see who to follow up with.
"""

from __future__ import annotations

import fcntl
import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent  # job_engine/
WAITLIST_FILE = BASE_DIR / '.data' / 'telegram_waitlist.json'
STORE_THREAD_LOCK = threading.RLock()
MAX_ENTRIES = 5000  # generous cap so a runaway loop cannot grow this unbounded


@contextmanager
def _store_lock():
    with STORE_THREAD_LOCK:
        WAITLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        lock_path = WAITLIST_FILE.with_suffix('.lock')
        with lock_path.open('a+', encoding='utf-8') as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load() -> list[dict[str, Any]]:
    if not WAITLIST_FILE.exists():
        return []
    try:
        data = json.loads(WAITLIST_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _save(entries: list[dict[str, Any]]) -> None:
    tmp = WAITLIST_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(entries, indent=2), encoding='utf-8')
    tmp.replace(WAITLIST_FILE)


def add_waitlist_entry(
    *,
    chat_id: str,
    email: str,
    experience: str = '',
    role_family: str = '',
) -> None:
    with _store_lock():
        entries = _load()
        entries.append({
            'chat_id': str(chat_id),
            'email': email.strip(),
            'experience': experience,
            'role_family': role_family,
            'created_at': time.time(),
        })
        if len(entries) > MAX_ENTRIES:
            entries = entries[-MAX_ENTRIES:]
        _save(entries)


def list_waitlist(limit: int = 20) -> list[dict[str, Any]]:
    """Newest first."""
    with _store_lock():
        entries = _load()
    return list(reversed(entries))[:max(1, min(int(limit), MAX_ENTRIES))]


def waitlist_count() -> int:
    with _store_lock():
        return len(_load())
