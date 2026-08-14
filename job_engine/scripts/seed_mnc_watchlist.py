#!/usr/bin/env python3
"""Seed the MNC-first collection base (Ashok's pivot, 2026-08-14).

Idempotent — runs on every deploy:
- Upserts one company-scoped fresher search per catalogue giant
  (app/mnc_watchlist.py) and marks the company watched.
- Puts every role-keyword search to sleep (disabled, never deleted).
- Company configs added from Telegram (/addcompany) are never touched.
- Asserts detail enrich mode = full (Ashok's sign-off: with focused volume,
  every job gets its detail page verified — experience, degrees, certs).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.mnc_watchlist import MNC_CATALOGUE, seed_watchlist
from app.runtime_settings import get_detail_enrich_mode, set_detail_enrich_mode


def main() -> None:
    with SessionLocal() as db:
        result = seed_watchlist(db)
    mode_before = get_detail_enrich_mode()
    if mode_before != 'full':
        set_detail_enrich_mode('full')
    print(
        f"MNC watchlist: {result['created']} created, "
        f"{result['existing']} already watched "
        f"(catalogue {len(MNC_CATALOGUE)}); "
        f"role searches put to sleep: {result['role_searches_slept']}."
    )
    print(
        'Detail enrich mode: full'
        + ('' if mode_before == 'full' else f' (was {mode_before})')
        + ' — every new job gets detail-page verification.'
    )


if __name__ == '__main__':
    raise SystemExit(main())
