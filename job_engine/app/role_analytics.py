"""Fair role analytics — reduce bias from early-started searches.

Older roles (e.g. Risks & Controls) accumulate more all-time jobs. Comparisons
must use the same time window (and optionally jobs/day) so new sectors aren't
punished for starting later.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import JobMaster, SearchConfig
from app.sectors import normalize_sector, sector_label
from app.signals import ALLOWED_WINDOWS, WINDOW_OPTIONS, _window_bounds


def roles_in_window(
    db: Session,
    *,
    days: int = 7,
    limit: int = 200,
    mode: str = 'count',
    sector: str | None = None,
) -> dict:
    """Rank roles by windowed job count (default) or jobs-per-active-day."""
    if days not in ALLOWED_WINDOWS:
        days = 7
    mode = 'rate' if mode == 'rate' else 'count'
    limit = max(1, min(limit, 300))
    sector = normalize_sector(sector)

    _d, recent_start, recent_end, _ps, _pe, by_scraped = _window_bounds(days)
    time_col = JobMaster.scraped_at if by_scraped else JobMaster.posted_date

    join_on = (
        (JobMaster.search_config_id == SearchConfig.id)
        & (time_col >= recent_start)
        & (time_col < recent_end)
    )
    if sector:
        join_on = join_on & (JobMaster.sector == sector)

    q = (
        select(
            SearchConfig.id,
            SearchConfig.name,
            SearchConfig.sector,
            func.count(JobMaster.id).label('n'),
            func.min(JobMaster.scraped_at).label('first_in_window'),
        )
        .outerjoin(JobMaster, join_on)
        .group_by(SearchConfig.id, SearchConfig.name, SearchConfig.sector)
    )
    if sector:
        q = q.where(SearchConfig.sector == sector)
    count_rows = db.execute(q).all()

    # Lifetime first scrape — coverage age (for honesty badge)
    first_all = dict(db.execute(
        select(JobMaster.search_config_id, func.min(JobMaster.scraped_at))
        .where(JobMaster.search_config_id.is_not(None))
        .group_by(JobMaster.search_config_id)
    ).all())

    now = datetime.now(timezone.utc)
    roles = []
    for sid, name, sector, n, first_in_window in count_rows:
        n = int(n or 0)
        first_ever = first_all.get(sid)
        if first_ever is not None and first_ever.tzinfo is None:
            first_ever = first_ever.replace(tzinfo=timezone.utc)
        if first_ever is None:
            active_days = 0
            collecting_since = None
        else:
            active_days = max(1, (now - first_ever).days + 1)
            collecting_since = first_ever.isoformat()
        # Rate inside the comparison window (fairer than lifetime)
        if by_scraped:
            window_days = max(1, int((recent_end - recent_start).total_seconds() // 86400) or 1)
        else:
            window_days = max(1, days if days > 0 else 1)
        rate = round(n / window_days, 2)
        roles.append({
            'search_id': sid,
            'name': name,
            'sector': sector or 'tech_digital',
            'sector_label': sector_label(sector or 'tech_digital'),
            'n': n,
            'rate': rate,
            'active_days': active_days,
            'collecting_since': collecting_since,
            'coverage_note': (
                f'Collecting {active_days}d'
                if active_days
                else 'No catches yet'
            ),
        })

    if mode == 'rate':
        roles.sort(key=lambda r: (-r['rate'], -r['n'], r['name']))
    else:
        roles.sort(key=lambda r: (-r['n'], -r['rate'], r['name']))

    roles = roles[:limit]
    max_n = max([r['n'] for r in roles] + [1])
    max_rate = max([r['rate'] for r in roles] + [0.01])

    # Common coverage floor: newest role that already has data
    with_data = [r for r in roles if r['collecting_since']]
    fair_hint = (
        'Counts use the same time window for every role — older searches '
        'no longer win just because they started earlier. Switch to '
        '“Per day” to compare pace.'
    )

    return {
        'days': days,
        'mode': mode,
        'window_options': [{'days': d, 'label': label} for d, label in WINDOW_OPTIONS],
        'max': max_n,
        'max_rate': max_rate,
        'total': len(roles),
        'roles': roles,
        'fair_hint': fair_hint,
        'with_data': len(with_data),
    }
