"""Per-step clocks for reverse / twist — we cannot cut what we do not measure."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Clock:
    def __init__(self, existing: dict | None = None):
        self.t0 = time.monotonic()
        self.marks: dict[str, float | str] = dict(existing or {})
        if 'started_at' not in self.marks:
            self.marks['started_at'] = utc_now_iso()
        self._laps: dict[str, float] = {}

    def start(self, name: str) -> None:
        self._laps[name] = time.monotonic()

    def stop(self, name: str) -> float:
        began = self._laps.pop(name, None)
        elapsed = 0.0 if began is None else round(time.monotonic() - began, 2)
        self.marks[name] = elapsed
        return elapsed

    def finish(self) -> dict:
        elapsed = round(time.monotonic() - self.t0, 2)
        if 'total' in self.marks:
            self.marks['twist_total'] = elapsed
        else:
            self.marks['total'] = elapsed
        self.marks['finished_at'] = utc_now_iso()
        return dict(self.marks)

    def snapshot(self) -> str:
        """Mid-run marks only — no total yet, so a live GET can show pace."""
        return json.dumps(dict(self.marks), separators=(',', ':'))

    def dumps(self) -> str:
        return json.dumps(self.finish(), separators=(',', ':'))


def load_marks(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def format_line(raw) -> str:
    """One Telegram line: ⏱ 2m 1s · download 18s · describe 70s · reel 8s"""
    marks = load_marks(raw)
    if not marks:
        return ''
    order = (
        'download', 'remux', 'describe', 'frames', 'refine', 'reel',
        'twist_prompt', 'twist_frames', 'omni', 'twist_total',
    )
    bits = []
    total = marks.get('total')
    if isinstance(total, (int, float)):
        bits.append(_human(float(total)))
    for key in order:
        value = marks.get(key)
        if isinstance(value, (int, float)) and value > 0:
            bits.append(f'{key} {_human(float(value))}')
    if len(bits) < 2 and not bits:
        return ''
    return '⏱ ' + ' · '.join(bits)


def _human(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f'{seconds:.0f}s' if seconds >= 10 else f'{seconds:.1f}s'
    minutes = int(seconds // 60)
    rest = int(round(seconds - minutes * 60))
    return f'{minutes}m {rest:02d}s'
