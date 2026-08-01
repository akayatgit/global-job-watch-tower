"""Runtime overrides shared by API + Celery (survives process restarts).

Used for the top-bar browser visibility toggle and LinkedIn block alerts.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import config as app_config

_LOCK = threading.Lock()
_PATH = app_config.BASE_DIR / '.data' / 'runtime_settings.json'
_ALERT_PATH = app_config.BASE_DIR / '.data' / 'alerts' / 'linkedin_block.json'


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read() -> dict[str, Any]:
    try:
        if _PATH.exists():
            return json.loads(_PATH.read_text())
    except Exception:
        pass
    return {}


def _write(data: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.replace(_PATH)


def get_headless() -> bool:
    """True = invisible Chrome (cooler). False = visible window for watching."""
    with _LOCK:
        data = _read()
    if 'headless' in data:
        return bool(data['headless'])
    return bool(app_config.HEADLESS)


def set_headless(headless: bool) -> bool:
    with _LOCK:
        data = _read()
        data['headless'] = bool(headless)
        data['headless_updated_at'] = _utcnow_iso()
        _write(data)
    return bool(headless)


def raise_linkedin_block(
    *,
    reason: str,
    url: str = '',
    run_id: int | None = None,
    page_title: str = '',
    page_text: str = '',
    http_status: int | None = None,
    html_excerpt: str = '',
) -> dict[str, Any]:
    """Persist a loud LinkedIn-block alert for the top bar (red mode)."""
    payload = {
        'active': True,
        'raised_at': _utcnow_iso(),
        'reason': reason,
        'url': url,
        'run_id': run_id,
        'page_title': (page_title or '')[:500],
        'page_text': (page_text or '')[:4000],
        'html_excerpt': (html_excerpt or '')[:6000],
        'http_status': http_status,
    }
    with _LOCK:
        _ALERT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ALERT_PATH.write_text(json.dumps(payload, indent=2))
        data = _read()
        data['alert_level'] = 'blocked'
        data['alert_updated_at'] = _utcnow_iso()
        _write(data)
    try:
        from app.tower_health import record_event_standalone
        record_event_standalone(
            'linkedin_block',
            run_id=run_id,
            detail=f'{reason} · {url}'[:1000],
        )
    except Exception:
        pass
    return payload


def dismiss_linkedin_block() -> None:
    with _LOCK:
        data = _read()
        data['alert_level'] = 'ok'
        data['alert_dismissed_at'] = _utcnow_iso()
        _write(data)
        if _ALERT_PATH.exists():
            try:
                raw = json.loads(_ALERT_PATH.read_text())
                raw['active'] = False
                raw['dismissed_at'] = _utcnow_iso()
                _ALERT_PATH.write_text(json.dumps(raw, indent=2))
            except Exception:
                _ALERT_PATH.unlink(missing_ok=True)


def get_linkedin_block() -> dict[str, Any] | None:
    try:
        if not _ALERT_PATH.exists():
            return None
        raw = json.loads(_ALERT_PATH.read_text())
        if not raw.get('active'):
            return None
        return raw
    except Exception:
        return None


def mark_plan_b_active(run_id: int | None = None, detail: str = '') -> None:
    """Orange attention — keyword filter used (Plan B)."""
    with _LOCK:
        data = _read()
        data['planb_at'] = _utcnow_iso()
        data['planb_run_id'] = run_id
        data['planb_detail'] = (detail or '')[:500]
        if data.get('alert_level') != 'blocked':
            data['alert_level'] = 'planb'
        _write(data)


def clear_plan_b() -> None:
    """Drop Plan B orange banner immediately (Ollama path is open again)."""
    with _LOCK:
        data = _read()
        changed = False
        if data.get('alert_level') == 'planb':
            data['alert_level'] = 'ok'
            changed = True
        if data.get('planb_at') or data.get('planb_detail') or data.get('planb_run_id') is not None:
            data.pop('planb_at', None)
            data.pop('planb_detail', None)
            data.pop('planb_run_id', None)
            data['planb_cleared_at'] = _utcnow_iso()
            changed = True
        if changed:
            _write(data)


def clear_plan_b_if_recovered() -> bool:
    """Clear Plan B banner as soon as Ollama is allowed again (not a 30‑min wait)."""
    from app.thermal import ollama_path_open
    if not ollama_path_open():
        return False
    with _LOCK:
        data = _read()
        sticky = data.get('alert_level') == 'planb' or bool(data.get('planb_at'))
    if sticky:
        clear_plan_b()
        return True
    return False


def clear_plan_b_if_stale(max_age_s: int = 1800) -> None:
    """Safety net: drop orange after 30 minutes even if recovery check missed."""
    clear_plan_b_if_recovered()
    with _LOCK:
        data = _read()
        ts = data.get('planb_at')
        if not ts:
            if data.get('alert_level') == 'planb':
                data['alert_level'] = 'ok'
                _write(data)
            return
        try:
            when = datetime.fromisoformat(ts)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - when).total_seconds()
        except Exception:
            age = 99999
        if age > max_age_s and data.get('alert_level') == 'planb':
            data['alert_level'] = 'ok'
            data.pop('planb_at', None)
            data.pop('planb_detail', None)
            data.pop('planb_run_id', None)
            _write(data)


def tower_alert_state(planb_recent: bool = False) -> dict[str, Any]:
    """Header traffic light: blocked > planb > ok."""
    clear_plan_b_if_stale()
    block = get_linkedin_block()
    with _LOCK:
        data = _read()
    if block:
        return {
            'level': 'blocked',
            'label': 'LinkedIn blocked us',
            'headless': get_headless(),
            'block': block,
        }
    # planb_recent only counts while Ollama is still blocked
    if data.get('alert_level') == 'planb' or planb_recent:
        return {
            'level': 'planb',
            'label': 'Plan B — without Ollama',
            'headless': get_headless(),
            'block': None,
            'planb_detail': data.get('planb_detail') or '',
            'planb_at': data.get('planb_at'),
        }
    return {
        'level': 'ok',
        'label': 'Tower healthy',
        'headless': get_headless(),
        'block': None,
    }
