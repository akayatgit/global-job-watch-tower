#!/usr/bin/env python3
"""Seed / refresh Watch Tower searches: once-daily staggered catalogue + sectors.

Idempotent: updates schedule/pages/sector for existing keyword matches; inserts missing.
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
from app.sectors import infer_sector
from app.seed_roles import (
    DEFAULT_MAX_PAGES,
    INDIA_GEO_ID,
    INDIA_LABEL,
    PRIORITY_MAX_PAGES,
    SECTOR_LIGHT_MAX_PAGES,
    all_seed_roles,
)

PRIORITY_KEYWORDS = {
    'ai product owner',
    'risk and control',
    'risk & control',
}

LIGHT_SECTORS = {
    'manufacturing_advanced',
    'healthcare',
    'green_economy',
    'logistics',
    'tourism',
}


def main() -> None:
    roles = all_seed_roles()
    created = updated = unchanged = 0

    with SessionLocal() as db:
        existing = {
            c.keywords.strip().lower(): c
            for c in db.execute(select(SearchConfig)).scalars()
        }
        by_name = {
            c.name.strip().lower(): c
            for c in db.execute(select(SearchConfig)).scalars()
        }

        for index, (name, keywords, sector) in enumerate(roles):
            cron = staggered_daily_cron(index, start_hour=5, interval_minutes=14)
            kw_key = keywords.strip().lower()
            if kw_key in PRIORITY_KEYWORDS:
                pages = PRIORITY_MAX_PAGES
            elif sector in LIGHT_SECTORS:
                pages = SECTOR_LIGHT_MAX_PAGES
            else:
                pages = DEFAULT_MAX_PAGES

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
                    sector=sector,
                )
                db.add(cfg)
                created += 1
                print(f'+ CREATE  [{sector:22s}] {name:40s}  {cron_to_human(cron)}  pages={pages}')
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
                want_sector = sector or infer_sector(cfg.name, cfg.keywords)
                if (cfg.sector or '') != want_sector:
                    cfg.sector = want_sector
                    changed = True
                if changed:
                    updated += 1
                    print(f'~ UPDATE  [{cfg.sector:22s}] {name:40s}  {cron_to_human(cron)}  pages={pages}')
                else:
                    unchanged += 1

        # Retag any leftover configs not in catalogue
        for cfg in db.execute(select(SearchConfig)).scalars():
            want = infer_sector(cfg.name, cfg.keywords)
            if (cfg.sector or 'software') in ('software', '') or cfg.sector not in {
                'tech_ai', 'tech_digital', 'manufacturing_advanced', 'healthcare',
                'green_economy', 'logistics', 'tourism',
            }:
                if cfg.sector != want:
                    cfg.sector = want
                    updated += 1
                    print(f'~ SECTOR  [{want:22s}] {cfg.name}')

        db.commit()

        total = db.execute(select(SearchConfig)).scalars().all()
        enabled = sum(1 for c in total if c.enabled)
        by_sec: dict[str, int] = {}
        for c in total:
            by_sec[c.sector or '?'] = by_sec.get(c.sector or '?', 0) + 1
        print()
        print(f'Done. created={created} updated={updated} unchanged={unchanged}')
        print(f'Tower searches: {len(total)} total, {enabled} enabled')
        for sid, n in sorted(by_sec.items(), key=lambda x: (-x[1], x[0])):
            print(f'  sector {sid}: {n}')
        print('Cadence: once daily, staggered from ~05:00 local every 14 minutes')


if __name__ == '__main__':
    raise SystemExit(main())
