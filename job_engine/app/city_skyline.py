"""City skyline payload — employers for cinematic night-city districts."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.cities import CITY_BY_ID, city_label, normalize_city_filter
from app.experience_bands import experience_clause, normalize_experience
from app.models import Company, JobMaster, SearchConfig
from app.sectors import SECTOR_BY_ID, normalize_sector
from app.signals import ALLOWED_WINDOWS, WINDOW_OPTIONS, _window_bounds

ROLES_PER_COMPANY = 5
MAX_JOB_CLUSTERS = 8
MAX_COS_PER_CLUSTER = 12


def _window_caption(window_days: int) -> str:
    """Human hook under the openings number (UI copy)."""
    if window_days == 0:
        return 'Openings in 24h'
    if window_days == 1:
        return 'Openings Today'
    if window_days == 7:
        return 'Openings this week'
    if window_days == 14:
        return 'Openings in 2 weeks'
    if window_days == 30:
        return 'Openings this month'
    return f'Openings in {window_days} days'


def compute_city_skyline(
    db: Session,
    city: str,
    window_days: int = 7,
    limit: int = 28,
) -> dict:
    city = normalize_city_filter(city) or ''
    empty = {
        'city': '',
        'label': '',
        'days': window_days if window_days in ALLOWED_WINDOWS else 7,
        'window_label': dict(WINDOW_OPTIONS).get(window_days, f'{window_days}d'),
        'window_caption': _window_caption(
            window_days if window_days in ALLOWED_WINDOWS else 7
        ),
        'window_options': [
            {'days': d, 'label': label} for d, label in WINDOW_OPTIONS
        ],
        'companies': [],
        'sectors': [],
        'stats': {'jobs': 0, 'companies': 0, 'max_n': 1},
    }
    if not city:
        return empty
    if window_days not in ALLOWED_WINDOWS:
        window_days = 7
    (_d, recent_start, recent_end, _ps, _pe, by_scraped) = _window_bounds(window_days)
    time_col = JobMaster.scraped_at if by_scraped else JobMaster.posted_date
    caption = _window_caption(window_days)
    window_label = dict(WINDOW_OPTIONS).get(window_days, f'{window_days}d')
    window_options = [{'days': d, 'label': label} for d, label in WINDOW_OPTIONS]

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
            **empty,
            'city': city,
            'label': label,
            'days': window_days,
            'window_label': window_label,
            'window_caption': caption,
            'window_options': window_options,
        }

    ids = [cid for cid, _, _ in co_rows]
    # Dominant sector per company
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

    # Role clusters — prefer Watch Tower search (role) names; else job title
    role_rows = db.execute(
        select(
            JobMaster.company_id,
            SearchConfig.name,
            func.count(JobMaster.id).label('n'),
        )
        .join(SearchConfig, SearchConfig.id == JobMaster.search_config_id)
        .where(
            time_col >= recent_start, time_col < recent_end,
            JobMaster.city_key == city,
            JobMaster.company_id.in_(ids),
            JobMaster.search_config_id.is_not(None),
        )
        .group_by(JobMaster.company_id, SearchConfig.name)
        .order_by(JobMaster.company_id, desc('n'))
    ).all()
    roles_by_co: dict[int, list[dict]] = defaultdict(list)
    for cid, rname, n in role_rows:
        bag = roles_by_co[cid]
        if len(bag) >= ROLES_PER_COMPANY:
            continue
        bag.append({'title': (rname or 'Role').strip(), 'n': int(n)})

    # Fill gaps with raw titles when a company has few/no search roles
    need_ids = [cid for cid in ids if len(roles_by_co[cid]) < ROLES_PER_COMPANY]
    if need_ids:
        title_rows = db.execute(
            select(
                JobMaster.company_id,
                JobMaster.title,
                func.count(JobMaster.id).label('n'),
            )
            .where(
                time_col >= recent_start, time_col < recent_end,
                JobMaster.city_key == city,
                JobMaster.company_id.in_(need_ids),
            )
            .group_by(JobMaster.company_id, JobMaster.title)
            .order_by(JobMaster.company_id, desc('n'))
        ).all()
        seen_titles: dict[int, set[str]] = defaultdict(set)
        for cid, _r in roles_by_co.items():
            for item in _r:
                seen_titles[cid].add(item['title'].lower())
        for cid, title, n in title_rows:
            bag = roles_by_co[cid]
            if len(bag) >= ROLES_PER_COMPANY:
                continue
            t = (title or 'Role').strip()
            key = t.lower()
            if key in seen_titles[cid]:
                continue
            # Skip if this title already covered by a search role substring
            if any(key in s or s in key for s in seen_titles[cid]):
                continue
            seen_titles[cid].add(key)
            bag.append({'title': t, 'n': int(n)})

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
            'roles': roles_by_co.get(cid, []),
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
        'window_label': window_label,
        'window_caption': caption,
        'window_options': window_options,
        'companies': companies,
        'sectors': sectors,
        'stats': {
            'jobs': total_jobs,
            'companies': len(companies),
            'max_n': max([c['n'] for c in companies] + [1]),
        },
    }


def compute_jobs_skyline(
    db: Session,
    *,
    sector: str | None = None,
    city: str | None = None,
    experience: str | None = None,
    limit: int = 120,
) -> dict:
    """Multi-city campus from the Jobs list filters.

    Groups the same filtered job set into city clusters — one building
    district per city that has openings. Used by Jobs → City view.
    """
    sector = normalize_sector(sector)
    city = normalize_city_filter(city)
    experience = normalize_experience(experience)
    limit = max(1, min(int(limit or 120), 300))

    q = (
        select(
            JobMaster.id,
            JobMaster.company_id,
            Company.name,
            JobMaster.city_key,
            JobMaster.sector,
            JobMaster.title,
            JobMaster.search_config_id,
            SearchConfig.name,
        )
        .outerjoin(Company, JobMaster.company_id == Company.id)
        .outerjoin(SearchConfig, SearchConfig.id == JobMaster.search_config_id)
        .order_by(desc(JobMaster.scraped_at))
        .limit(limit)
    )
    if sector:
        q = q.where(JobMaster.sector == sector)
    if city:
        q = q.where(JobMaster.city_key == city)
    exp = experience_clause(experience)
    if exp is not None:
        q = q.where(exp)

    rows = db.execute(q).all()

    # city → company_id → agg
    by_city: dict[str, dict[int, dict]] = defaultdict(dict)
    for (
        _jid, cid, cname, ckey, jsector, title, _sid, role_name,
    ) in rows:
        if not cid:
            continue
        key = (ckey or 'other').strip() or 'other'
        bag = by_city[key]
        if cid not in bag:
            bag[cid] = {
                'company_id': cid,
                'name': cname or 'Company',
                'n': 0,
                'sectors': defaultdict(int),
                'roles': defaultdict(int),
            }
        entry = bag[cid]
        entry['n'] += 1
        if jsector:
            entry['sectors'][jsector] += 1
        rlabel = (role_name or title or 'Role').strip()
        if rlabel:
            entry['roles'][rlabel] += 1

    clusters = []
    total_jobs = 0
    total_cos = 0
    for ckey, cos in by_city.items():
        companies = []
        city_jobs = 0
        for cid, entry in cos.items():
            city_jobs += entry['n']
            sid = 'tech_digital'
            if entry['sectors']:
                sid = max(entry['sectors'].items(), key=lambda x: x[1])[0]
            meta = SECTOR_BY_ID.get(sid, {})
            role_items = sorted(
                entry['roles'].items(), key=lambda x: -x[1],
            )[:ROLES_PER_COMPANY]
            companies.append({
                'company_id': cid,
                'name': entry['name'],
                'n': entry['n'],
                'sector_id': sid,
                'sector_label': meta.get('label') or sid.replace('_', ' ').title(),
                'roles': [{'title': t, 'n': n} for t, n in role_items],
            })
        companies.sort(key=lambda c: -c['n'])
        companies = companies[:MAX_COS_PER_CLUSTER]
        total_jobs += city_jobs
        total_cos += len(companies)
        clusters.append({
            'city': ckey,
            'label': city_label(ckey),
            'companies': companies,
            'stats': {
                'jobs': city_jobs,
                'companies': len(companies),
                'max_n': max([c['n'] for c in companies] + [1]),
            },
        })

    clusters.sort(key=lambda c: -c['stats']['jobs'])
    clusters = clusters[:MAX_JOB_CLUSTERS]

    return {
        'mode': 'jobs',
        'sector': sector or '',
        'city': city or '',
        'experience': experience or '',
        'clusters': clusters,
        'stats': {
            'jobs': total_jobs,
            'companies': total_cos,
            'cities': len(clusters),
            'max_n': max(
                [c['stats']['max_n'] for c in clusters] + [1],
            ),
        },
    }
