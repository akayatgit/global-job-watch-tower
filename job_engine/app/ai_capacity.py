"""Shared Ollama capacity gate — scrape wins; Hermes/Ask yield when busy or warm."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.thermal import snapshot
from app.tower_health import compute_vitals


def compute_ai_capacity(db: Session) -> dict:
    """Return whether secondary AI (Hermes / VIGIL Ask) may use Ollama now."""
    vitals = compute_vitals(db)
    snap = snapshot()

    reasons: list[str] = []
    cool_in_secs = 0.0

    if vitals.ollama_live:
        reasons.append('Tower is using Ollama for a live search filter')
        cool_in_secs = max(cool_in_secs, 120.0)

    if snap.level in ('warm', 'hot', 'critical'):
        reasons.append(f'PC heat is {snap.level} ({snap.detail})')
        cool_in_secs = max(cool_in_secs, snap.break_s or 60.0)

    # Active scrape without ollama pulse still deserves caution when critical
    if snap.level == 'critical':
        reasons.append('Critical heat — collection and cooling first')

    allowed = len(reasons) == 0
    if allowed:
        reason = 'Cool and idle — Ask / Hermes may use Ollama'
    else:
        reason = '; '.join(reasons)

    return {
        'allowed': allowed,
        'reason': reason,
        'cool_in_secs': int(cool_in_secs),
        'heat_level': snap.level,
        'heat_detail': snap.detail,
        'heat_c': vitals.heat_c,
        'ollama_live': vitals.ollama_live,
        'phase_label': vitals.phase_label,
        'model_hint': 'qwen3.5:4b-hermes',
        'priority': 'scrape_first',
    }
