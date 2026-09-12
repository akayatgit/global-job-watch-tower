"""Reverse prompt owns the worker lane — promptscan waits.

Ashok (2026-09-11): /igtovid is more important than /promptscan. The
moment the reverse workflow starts, break any in-flight collect/score
run and refuse new scans for 15 minutes so Chrome, Celery and Hermes
stay free for the clip.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from app import config

logger = logging.getLogger(__name__)

HOLD_S = 15 * 60
HOLD_KEY = 'prompt-tower:scan-hold-until'
SCAN_TASKS = (
    'app.tasks.daily_prompt_pipeline',
    'app.tasks.score_pending_prompts',
)
_FILE = Path(getattr(config, 'BASE_DIR', Path('.'))) / '.data' / 'scan_hold_until'


class ReverseHold(RuntimeError):
    """Scan aborted because reverse prompt has the lane."""


def _redis():
    import redis

    return redis.Redis.from_url(
        config.REDIS_URL, socket_connect_timeout=2, socket_timeout=2,
    )


def _set_until(until: float) -> None:
    ttl = max(60, int(until - time.time()) + 60)
    try:
        _redis().set(HOLD_KEY, f'{until:.3f}', ex=ttl)
    except Exception as exc:
        logger.warning('scan hold redis write failed: %s', exc)
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(f'{until:.3f}', encoding='utf-8')
    except Exception as exc:
        logger.warning('scan hold file write failed: %s', exc)


def _get_until() -> float:
    vals: list[float] = []
    try:
        raw = _redis().get(HOLD_KEY)
        if raw:
            vals.append(float(raw))
    except Exception:
        pass
    try:
        if _FILE.is_file():
            vals.append(float(_FILE.read_text(encoding='utf-8').strip()))
    except Exception:
        pass
    return max(vals) if vals else 0.0


def remaining_s(*, now: float | None = None) -> int:
    now = time.time() if now is None else now
    return max(0, int(_get_until() - now))


def is_held(*, now: float | None = None) -> bool:
    return remaining_s(now=now) > 0


def raise_if_held(*, now: float | None = None) -> None:
    left = remaining_s(now=now)
    if left > 0:
        raise ReverseHold(f'reverse owns the lane for {left}s')


def hold_scan(*, seconds: int = HOLD_S, now: float | None = None) -> int:
    """Set or extend the hold. A second /igtovid refreshes the 15 minutes."""
    now = time.time() if now is None else now
    until = now + max(1, int(seconds))
    current = _get_until()
    if until < current:
        until = current
    _set_until(until)
    return int(until - now)


def clear_hold() -> None:
    """Drop the reverse hold — CI/tests must not leak a 15-min lane lock."""
    try:
        _redis().delete(HOLD_KEY)
    except Exception:
        pass
    try:
        if _FILE.is_file():
            _FILE.unlink()
    except Exception as exc:
        logger.warning('scan hold file clear failed: %s', exc)


def revoke_scan_tasks(*, control=None) -> int:
    """SIGTERM any running / queued collect+score task. Reverse stays."""
    if control is None:
        from app.celery_app import celery

        control = celery.control
    ids: list[str] = []
    try:
        inspect = control.inspect(timeout=2)
        blobs = [inspect.active(), inspect.reserved(), inspect.scheduled()]
    except Exception as exc:
        logger.warning('scan hold inspect failed: %s', exc)
        blobs = []
    for blob in blobs:
        if not blob:
            continue
        for _worker, items in blob.items():
            for item in items or []:
                request = item.get('request') if isinstance(item, dict) else None
                name = (item.get('name') if isinstance(item, dict) else None) or (
                    request.get('name') if isinstance(request, dict) else None
                )
                tid = (item.get('id') if isinstance(item, dict) else None) or (
                    request.get('id') if isinstance(request, dict) else None
                )
                if name in SCAN_TASKS and tid:
                    ids.append(str(tid))
    for tid in ids:
        try:
            control.revoke(tid, terminate=True, signal='SIGTERM')
        except Exception as exc:
            logger.warning('scan hold revoke %s failed: %s', tid, exc)
    return len(ids)


def break_prompt_scan(*, seconds: int = HOLD_S, control=None) -> dict:
    """Call the moment /igtovid starts. Hold 15 min + kill the scan."""
    held = hold_scan(seconds=seconds)
    revoked = revoke_scan_tasks(control=control)
    logger.info('promptscan broken for reverse — hold %ss, revoked %s', held, revoked)
    return {'held_s': held, 'revoked': revoked}
