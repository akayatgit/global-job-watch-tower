#!/usr/bin/env python3
"""Backfill JobMaster.city_key from raw location (+ title) strings."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.cities import normalize_city
from app.db import SessionLocal
from app.models import JobMaster


def main() -> None:
    db = SessionLocal()
    try:
        rows = db.execute(select(JobMaster.id, JobMaster.location, JobMaster.title)).all()
        updated = 0
        for jid, location, title in rows:
            key = normalize_city(location, title)
            job = db.get(JobMaster, jid)
            if job is None:
                continue
            if job.city_key != key:
                job.city_key = key
                updated += 1
        db.commit()
        print(f'Backfilled city_key on {updated}/{len(rows)} jobs')
    finally:
        db.close()


if __name__ == '__main__':
    main()
