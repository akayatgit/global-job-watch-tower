"""City skyline payload — employers for cinematic night-city districts."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.cities import CITY_BY_ID, normalize_city_filter
from app.models import Company, JobMaster
from app.sectors import SECTOR_BY_ID
from app.signals import ALLOWED_WINDOWS, _window_bounds


def compute_city_skyline(
    db: Session,
    city: str,
    window_days: int = 7,
    limit: int = 28,
) -> dict:
    city = normalize_city_filter(city) or ''
    if not city:
        return {
            'city': '',
            'label': '',
            'companies': [],
            'sectors': [],
            'stats': {'jobs': 0, 'companies': 0},
        }
    if window_days not in ALLOWED_WINDOWS:
        window_days = 7
    (_d, recent_start, recent_end, _ps, _pe, by_scraped) = _window_bounds(window_days)
    time_col = JobMaster.scraped_at if by_scraped else JobMaster.posted_date

    # Totals per company in this city
    co_rows = db.execute(
        select(
            Company.id, Company.name, func.count(JobMaster.id).label('n'),
        )
        .join(JobMaster, JobMaster.company_id == Company.id)
        .where(
            time_col >= recent_start, time_col < recent_end,
            JobMaster.city_key == city,
        )
        .group_by(Company.id, Company.name)
        .order_by(desc('n'))
        .limit(limit)
    ).all()
    if not co_rows:
        label = CITY_BY_ID.get(city, {}).get('label') or city.title()
        return {
            'city': city,
            'label': label,
            'days': window_days,
            'companies': [],
            'sectors': [],
            'stats': {'jobs': 0, 'companies': 0},
        }

    ids = [cid for cid, _, _ in co_rows]
    # Dominant sector per company (most jobs in that sector in this city/window)
    sec_rows = db.execute(
        select(
            JobMaster.company_id, JobMaster.sector,
            func.count(JobMaster.id).label('n'),
        )
        .where(
            time_col >= recent_start, time_col < recent_end,
            JobMaster.city_key == city,
            JobMaster.company_id.in_(ids),
        )
        .group_by(JobMaster.company_id, JobMaster.sector)
        .order_by(JobMaster.company_id, desc('n'))
    ).all()
    dominant: dict[int, str] = {}
    for cid, sector, _n in sec_rows:
        if cid not in dominant and sector:
            dominant[cid] = sector

    companies = []
    by_sector: dict[str, int] = defaultdict(int)
    total_jobs = 0
    for cid, name, n in co_rows:
        sid = dominant.get(cid) or 'tech_digital'
        meta = SECTOR_BY_ID.get(sid, {})
        companies.append({
            'company_id': cid,
            'name': name or 'Company',
            'n': int(n),
            'sector_id': sid,
            'sector_label': meta.get('label') or sid.replace('_', ' ').title(),
        })
        by_sector[sid] += int(n)
        total_jobs += int(n)

    sectors = [
        {
            'id': sid,
            'label': SECTOR_BY_ID.get(sid, {}).get('label') or sid,
            'n': n,
        }
        for sid, n in sorted(by_sector.items(), key=lambda x: -x[1])
    ]
    label = CITY_BY_ID.get(city, {}).get('label') or city.title()
    return {
        'city': city,
        'label': label,
        'days': window_days,
        'companies': companies,
        'sectors': sectors,
        'stats': {
            'jobs': total_jobs,
            'companies': len(companies),
            'max_n': max([c['n'] for c in companies] + [1]),
        },
    }
