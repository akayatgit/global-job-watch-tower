#!/usr/bin/env python3
"""Seed / refresh Watch Tower dual-track searches (Fresher + Market Signal).

Idempotent: upserts by name (preferred) or keywords+track; disables configs
not present in the canonical catalogue so seed owns truth.
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
    PRIORITY_KEYWORD_NEEDLES,
    PRIORITY_MAX_PAGES,
    SECTOR_LIGHT_MAX_PAGES,
    SIGNAL_MAX_PAGES,
    all_seed_roles,
)

LIGHT_SECTORS = {
    'manufacturing_advanced',
    'healthcare',
    'green_economy',
    'logistics',
    'tourism',
}


def _pages_for(keywords: str, sector: str, track: str) -> int:
    if track == 'signal':
        return SIGNAL_MAX_PAGES
    if sector in LIGHT_SECTORS:
        return SECTOR_LIGHT_MAX_PAGES
    kw = keywords.lower()
    if any(n in kw for n in PRIORITY_KEYWORD_NEEDLES):
        return PRIORITY_MAX_PAGES
    return DEFAULT_MAX_PAGES


def main() -> None:
    roles = all_seed_roles()
    created = updated = unchanged = disabled = 0
    catalogue_names = {name.strip().lower() for name, *_ in roles}

    with SessionLocal() as db:
        by_name = {
            c.name.strip().lower(): c
            for c in db.execute(select(SearchConfig)).scalars()
        }
        # Secondary index: keywords|track
        by_kw_track = {
            f'{c.keywords.strip().lower()}|{(c.track or "fresher")}': c
            for c in db.execute(select(SearchConfig)).scalars()
        }

        for index, (name, keywords, sector, exp_filter, track) in enumerate(roles):
            # Fresher flywheel starts ~05:00; Market Signal staggered later (~14:00+)
            if track == 'signal':
                cron = staggered_daily_cron(index, start_hour=14, interval_minutes=18)
            else:
                cron = staggered_daily_cron(index, start_hour=5, interval_minutes=14)
            pages = _pages_for(keywords, sector, track)
            kw_key = keywords.strip().lower()
            name_key = name.strip().lower()
            exp_norm = (exp_filter or '').strip() or None

            cfg = by_name.get(name_key)
            if cfg is None:
                cfg = by_kw_track.get(f'{kw_key}|{track}')

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
                    experience_filter=exp_norm,
                    track=track,
                )
                db.add(cfg)
                created += 1
                print(
                    f'+ CREATE  [{track:7s}|{sector:22s}] {name:48s}  '
                    f'f_E={exp_norm or "-"}  {cron_to_human(cron)}  pages={pages}'
                )
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
                if (cfg.experience_filter or None) != exp_norm:
                    cfg.experience_filter = exp_norm
                    changed = True
                if (cfg.track or 'fresher') != track:
                    cfg.track = track
                    changed = True
                if changed:
                    updated += 1
                    print(
                        f'~ UPDATE  [{track:7s}|{cfg.sector:22s}] {name:48s}  '
                        f'f_E={exp_norm or "-"}  {cron_to_human(cron)}  pages={pages}'
                    )
                else:
                    unchanged += 1

        # Disable leftovers not in the new catalogue (seed owns truth)
        for cfg in db.execute(select(SearchConfig)).scalars():
            if cfg.name.strip().lower() not in catalogue_names:
                if cfg.enabled:
                    cfg.enabled = False
                    disabled += 1
                    print(f'- DISABLE (not in catalogue)  {cfg.name}')

        db.commit()

        total = db.execute(select(SearchConfig)).scalars().all()
        enabled = [c for c in total if c.enabled]
        by_track: dict[str, int] = {}
        by_sec: dict[str, int] = {}
        with_fe = 0
        for c in enabled:
            by_track[c.track or '?'] = by_track.get(c.track or '?', 0) + 1
            by_sec[c.sector or '?'] = by_sec.get(c.sector or '?', 0) + 1
            if c.experience_filter:
                with_fe += 1
        print()
        print(
            f'Done. created={created} updated={updated} unchanged={unchanged} '
            f'disabled={disabled}'
        )
        print(f'Tower searches: {len(total)} total, {len(enabled)} enabled '
              f'({with_fe} with LinkedIn f_E)')
        for tid, n in sorted(by_track.items(), key=lambda x: (-x[1], x[0])):
            print(f'  track {tid}: {n}')
        for sid, n in sorted(by_sec.items(), key=lambda x: (-x[1], x[0])):
            print(f'  sector {sid}: {n}')
        print('Cadence: Fresher ~05:00 / 14m · Market Signal ~14:00 / 18m')


if __name__ == '__main__':
    raise SystemExit(main())
