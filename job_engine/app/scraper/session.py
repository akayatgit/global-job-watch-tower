"""Sync the LinkedIn login session from the user's real Chrome profile
into a dedicated bot profile used by Scrapling (user_data_dir).

Ported from the original app.py proof of concept, hardened for Watch Tower:
clear stale Chrome singleton locks, report what synced, fail loud when
cookies are missing.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from app import config


@dataclass
class SessionSyncResult:
    copied: bool
    cookies_ok: bool
    detail: str


def _mark_clean_exit(dst_default: Path):
    """Rewrite the bot profile's Preferences so Chrome believes it exited
    cleanly — otherwise every launch shows the "Restore pages?" bubble
    (we kill the browser between runs, and the copied Preferences may
    carry a Crashed exit state from the real profile)."""
    prefs_path = dst_default / 'Preferences'
    try:
        data = json.loads(prefs_path.read_text()) if prefs_path.exists() else {}
    except Exception:
        data = {}
    profile = data.setdefault('profile', {})
    profile['exit_type'] = 'Normal'
    profile['exited_cleanly'] = True
    # 5 = open the New Tab page; never try to restore the previous session
    data.setdefault('session', {})['restore_on_startup'] = 5
    try:
        prefs_path.parent.mkdir(parents=True, exist_ok=True)
        prefs_path.write_text(json.dumps(data))
    except Exception:
        pass


def _clear_singleton_locks(bot_root: Path):
    """Remove Chrome Singleton* files that block relaunch after a crash/kill."""
    for name in ('SingletonLock', 'SingletonCookie', 'SingletonSocket'):
        path = bot_root / name
        try:
            if path.exists() or path.is_symlink():
                path.unlink(missing_ok=True)
        except Exception:
            pass


def _copy_sqlite(src: Path, dst: Path) -> bool:
    """Copy a possibly-locked Chrome SQLite DB safely."""
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_db = Path(tmp) / 'db'
            try:
                src_conn = sqlite3.connect(f'file:{src}?mode=ro', uri=True)
                dst_conn = sqlite3.connect(tmp_db)
                src_conn.backup(dst_conn)
                dst_conn.close()
                src_conn.close()
            except Exception:
                shutil.copy2(src, tmp_db)
            shutil.copy2(tmp_db, dst)
        return True
    except Exception:
        return False


def _cookies_present(dst_default: Path) -> bool:
    for rel in ('Network/Cookies', 'Cookies'):
        path = dst_default / rel
        if path.exists() and path.stat().st_size > 0:
            return True
    return False


def sync_linkedin_session() -> SessionSyncResult:
    """Pull LinkedIn cookies/session from the real Chrome into the bot profile."""
    src_default = config.CHROME_SOURCE_PROFILE / 'Default'
    dst_root = config.CHROME_BOT_PROFILE
    dst_default = dst_root / 'Default'
    dst_default.mkdir(parents=True, exist_ok=True)

    _clear_singleton_locks(dst_root)

    if not src_default.exists():
        return SessionSyncResult(
            copied=False,
            cookies_ok=_cookies_present(dst_default),
            detail=f'Source Chrome profile missing at {src_default}',
        )

    local_state = config.CHROME_SOURCE_PROFILE / 'Local State'
    if local_state.exists():
        shutil.copy2(local_state, dst_root / 'Local State')

    copied_parts: list[str] = []
    for rel in (
        'Network/Cookies',
        'Cookies',
        'Network/Cookies-journal',
        'Cookies-journal',
        'Preferences',
        'Secure Preferences',
    ):
        src = src_default / rel
        if src.exists() and src.is_file():
            if src.name.startswith('Cookies'):
                if _copy_sqlite(src, dst_default / rel):
                    copied_parts.append(rel)
            else:
                (dst_default / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst_default / rel)
                copied_parts.append(rel)

    for rel in ('Local Storage', 'Session Storage'):
        src = src_default / rel
        dst = dst_default / rel
        if src.exists():
            if dst.exists():
                shutil.rmtree(dst, ignore_errors=True)
            try:
                shutil.copytree(src, dst, dirs_exist_ok=True)
                copied_parts.append(rel)
            except Exception:
                pass

    # Never carry over tab-restore data: it feeds the "Restore pages?" bubble
    shutil.rmtree(dst_default / 'Sessions', ignore_errors=True)
    _mark_clean_exit(dst_default)
    _clear_singleton_locks(dst_root)

    cookies_ok = _cookies_present(dst_default)
    if copied_parts and cookies_ok:
        detail = f'Synced {len(copied_parts)} profile item(s); cookies ready.'
    elif cookies_ok:
        detail = 'Using existing bot-profile cookies (nothing new copied).'
    else:
        detail = (
            'No LinkedIn cookies in bot profile. Open Chrome, log into LinkedIn, '
            'then rerun so the session can sync.'
        )
    return SessionSyncResult(
        copied=bool(copied_parts),
        cookies_ok=cookies_ok,
        detail=detail,
    )
