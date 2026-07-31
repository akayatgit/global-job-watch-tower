#!/usr/bin/env python3
"""Seed / refresh Watch Tower searches: once-daily staggered fresher catalogue.

Idempotent: updates schedule/pages for existing keyword matches; inserts missing.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.db import SessionLocal
from app.models import SearchConfig
from app.schedule import cron_to_human, staggered_daily_cron
from app.seed_roles import (
    DEFAULT_MAX_PAGES,
    FRESHER_MAJOR_ROLES,
    INDIA_GEO_ID,
    INDIA_LABEL,
    PRIORITY_MAX_PAGES,
)

PRIORITY_KEYWORDS = {
    'ai product owner',
    'risk and control',
    'risk & control',
}


def main() -> None:
    roles = FRESHER_MAJOR_ROLES
    created = updated = unchanged = 0

    with SessionLocal() as db:
        existing = {
            c.keywords.strip().lower(): c
            for c in db.execute(select(SearchConfig)).scalars()
        }
        # Also index by normalized name for the two pilot rows that used "risk & control"
        by_name = {
            c.name.strip().lower(): c
            for c in db.execute(select(SearchConfig)).scalars()
        }

        for index, (name, keywords) in enumerate(roles):
            cron = staggered_daily_cron(index, start_hour=5, interval_minutes=14)
            kw_key = keywords.strip().lower()
            pages = PRIORITY_MAX_PAGES if kw_key in PRIORITY_KEYWORDS else DEFAULT_MAX_PAGES

            cfg = existing.get(kw_key)
            if cfg is None and name.strip().lower() in by_name:
                cfg = by_name[name.strip().lower()]

            if cfg is None:
                cfg = SearchConfig(
                    name=name,
                    keywords=keywords,
                    geo_id=INDIA_GEO_ID,
                    location_label=INDIA_LABEL,
                    schedule_cron=cron,
                    max_pages=pages,
                    enabled=True,
                    sector='software',
                )
                db.add(cfg)
                created += 1
                print(f'+ CREATE  {name:40s}  {cron_to_human(cron)}  pages={pages}')
            else:
                changed = False
                if cfg.name != name:
                    cfg.name = name
                    changed = True
                if cfg.keywords.strip().lower() != kw_key:
                    cfg.keywords = keywords
                    changed = True
                if cfg.schedule_cron != cron:
                    cfg.schedule_cron = cron
                    changed = True
                if cfg.max_pages != pages:
                    cfg.max_pages = pages
                    changed = True
                if not cfg.location_label:
                    cfg.location_label = INDIA_LABEL
                    changed = True
                if cfg.geo_id != INDIA_GEO_ID:
                    cfg.geo_id = INDIA_GEO_ID
                    changed = True
                if not cfg.enabled:
                    cfg.enabled = True
                    changed = True
                if changed:
                    updated += 1
                    print(f'~ UPDATE  {name:40s}  {cron_to_human(cron)}  pages={pages}')
                else:
                    unchanged += 1

        db.commit()

        total = db.execute(select(SearchConfig)).scalars().all()
        enabled = sum(1 for c in total if c.enabled)
        print()
        print(f'Done. created={created} updated={updated} unchanged={unchanged}')
        print(f'Tower searches: {len(total)} total, {enabled} enabled')
        print('Cadence: once daily, staggered from ~05:00 local every 14 minutes')
        print('Filter: LinkedIn past 24 hours (f_TPR=r86400) — one successful daily pass covers the day')


if __name__ == '__main__':
    main()
