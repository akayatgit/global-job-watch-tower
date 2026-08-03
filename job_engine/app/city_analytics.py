"""City hiring signals and two-city comparisons."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cities import (
    CRITICAL_CITIES,
    METRO_CITY_IDS,
    city_label,
    normalize_city_filter,
    city_options,
)
from app.models import Company, JobMaster, SearchConfig
from app.sectors import normalize_sector
from app.signals import (
    ALLOWED_WINDOWS,
    WINDOW_OPTIONS,
    _count_jobs,
    _window_bounds,
    _window_labels,
)


@dataclass
class CitySignal:
    city: str
    label: str
    recent: int
    prior: int

    @property
    def delta(self) -> int:
        return self.recent - self.prior

    @property
    def delta_pct(self) -> float | None:
        if self.prior <= 0:
            return None if self.recent <= 0 else 100.0
        return (self.recent - self.prior) / self.prior * 100.0


def compute_city_signals(
    db: Session,
    window_days: int = 7,
    sector: str | None = None,
    experience: str | None = None,
) -> dict:
    """Hiring velocity by city — volume + growth ranking."""
    from app.experience_bands import experience_options, normalize_experience

    if window_days not in ALLOWED_WINDOWS:
        window_days = 7
    sector = normalize_sector(sector)
    experience = normalize_experience(experience)
    (window_days, recent_start, recent_end, prior_start, prior_end,
     by_scraped) = _window_bounds(window_days)

    # All known catalogue keys so empty metros still appear with 0
    keys = [c['id'] for c in CRITICAL_CITIES]
    signals: list[CitySignal] = []
    for key in keys:
        recent = _count_jobs(
            db, recent_start, recent_end, sector=sector, city=key,
            experience=experience, by_scraped=by_scraped,
        )
        prior = _count_jobs(
            db, prior_start, prior_end, sector=sector, city=key,
            experience=experience, by_scraped=by_scraped,
        )
        if recent == 0 and prior == 0 and key not in METRO_CITY_IDS:
            # Skip empty remote/india/other unless they have data
            continue
        signals.append(CitySignal(
            city=key, label=city_label(key), recent=recent, prior=prior,
        ))

    by_volume = sorted(signals, key=lambda c: (c.recent, c.delta), reverse=True)
    growing = sorted(
        [c for c in signals if c.delta > 0],
        key=lambda c: (c.delta, c.recent),
        reverse=True,
    )
    slowing = sorted(
        [c for c in signals if c.delta < 0],
        key=lambda c: (c.delta, -c.recent),
    )

    recent_total = _count_jobs(
        db, recent_start, recent_end, sector=sector,
        experience=experience, by_scraped=by_scraped,
    )
    prior_total = _count_jobs(
        db, prior_start, prior_end, sector=sector,
        experience=experience, by_scraped=by_scraped,
    )
    win_label, prior_label = _window_labels(window_days)
    if recent_total == 0 and prior_total == 0:
        headline = 'No openings in this window yet — cities light up after catches.'
    elif by_volume and by_volume[0].recent > 0:
        top = by_volume[0]
        headline = (
            f'{top.label} leads hiring ({top.recent} openings {win_label}).'
        )
        if growing and growing[0].delta > 0:
            g = growing[0]
            headline += f' Fastest rise: {g.label} (+{g.delta} vs {prior_label}).'
    else:
        headline = f'{recent_total} openings {win_label} — city split still thin.'

    def _row(c: CitySignal) -> dict:
        return {
            'city': c.city,
            'label': c.label,
            'recent': c.recent,
            'prior': c.prior,
            'delta': c.delta,
            'delta_pct': c.delta_pct,
        }

    return {
        'days': window_days,
        'sector': sector or '',
        'experience': experience or '',
        'city_options': city_options(),
        'experience_options': experience_options(),
        'window_options': [{'days': d, 'label': label} for d, label in WINDOW_OPTIONS],
        'recent_total': recent_total,
        'prior_total': prior_total,
        'headline': headline,
        'cities': [_row(c) for c in by_volume],
        'growing': [_row(c) for c in growing[:8]],
        'slowing': [_row(c) for c in slowing[:5]],
        'max': max([c.recent for c in by_volume] + [1]),
    }


def _city_slice(
    db: Session,
    city: str,
    recent_start,
    recent_end,
    prior_start,
    prior_end,
    by_scraped: bool,
    sector: str | None,
    experience: str | None = None,
) -> dict:
    from app.experience_bands import experience_clause

    recent = _count_jobs(
        db, recent_start, recent_end, city=city, sector=sector,
        experience=experience, by_scraped=by_scraped,
    )
    prior = _count_jobs(
        db, prior_start, prior_end, city=city, sector=sector,
        experience=experience, by_scraped=by_scraped,
    )
    delta = recent - prior
    if prior <= 0:
        delta_pct = None if recent <= 0 else 100.0
    else:
        delta_pct = delta / prior * 100.0

    time_col = JobMaster.scraped_at if by_scraped else JobMaster.posted_date
    role_q = (
        select(
            SearchConfig.id, SearchConfig.name,
            func.count(JobMaster.id).label('n'),
        )
        .join(JobMaster, JobMaster.search_config_id == SearchConfig.id)
        .where(
            JobMaster.city_key == city,
            time_col >= recent_start,
            time_col < recent_end,
        )
        .group_by(SearchConfig.id, SearchConfig.name)
        .order_by(func.count(JobMaster.id).desc())
        .limit(5)
    )
    if sector:
        role_q = role_q.where(JobMaster.sector == sector)
    exp = experience_clause(experience)
    if exp is not None:
        role_q = role_q.where(exp)
    roles = [
        {'search_id': sid, 'name': name, 'n': int(n)}
        for sid, name, n in db.execute(role_q).all()
    ]

    co_q = (
        select(
            Company.id, Company.name,
            func.count(JobMaster.id).label('n'),
        )
        .join(JobMaster, JobMaster.company_id == Company.id)
        .where(
            JobMaster.city_key == city,
            time_col >= recent_start,
            time_col < recent_end,
        )
        .group_by(Company.id, Company.name)
        .order_by(func.count(JobMaster.id).desc())
        .limit(5)
    )
    if sector:
        co_q = co_q.where(JobMaster.sector == sector)
    if exp is not None:
        co_q = co_q.where(exp)
    companies = [
        {'company_id': cid, 'name': name, 'n': int(n)}
        for cid, name, n in db.execute(co_q).all()
    ]

    return {
        'city': city,
        'label': city_label(city),
        'recent': recent,
        'prior': prior,
        'delta': delta,
        'delta_pct': delta_pct,
        'top_roles': roles,
        'top_companies': companies,
    }


def compare_cities(
    db: Session,
    city_a: str,
    city_b: str,
    window_days: int = 7,
    sector: str | None = None,
    experience: str | None = None,
) -> dict:
    """Side-by-side hiring snapshot for two cities."""
    from app.experience_bands import experience_options, normalize_experience

    if window_days not in ALLOWED_WINDOWS:
        window_days = 7
    a = normalize_city_filter(city_a)
    b = normalize_city_filter(city_b)
    if not a or not b:
        return {
            'error': 'Pick two cities to compare',
            'days': window_days,
            'city_options': city_options(),
            'experience_options': experience_options(),
            'window_options': [{'days': d, 'label': label} for d, label in WINDOW_OPTIONS],
        }
    if a == b:
        return {
            'error': 'Pick two different cities',
            'days': window_days,
            'a': a,
            'b': b,
            'city_options': city_options(),
            'experience_options': experience_options(),
            'window_options': [{'days': d, 'label': label} for d, label in WINDOW_OPTIONS],
        }
    sector = normalize_sector(sector)
    experience = normalize_experience(experience)
    (window_days, recent_start, recent_end, prior_start, prior_end,
     by_scraped) = _window_bounds(window_days)

    left = _city_slice(
        db, a, recent_start, recent_end, prior_start, prior_end,
        by_scraped, sector, experience,
    )
    right = _city_slice(
        db, b, recent_start, recent_end, prior_start, prior_end,
        by_scraped, sector, experience,
    )
    leader = None
    if left['recent'] > right['recent']:
        leader = left['label']
    elif right['recent'] > left['recent']:
        leader = right['label']

    return {
        'days': window_days,
        'sector': sector or '',
        'city_options': city_options(),
        'window_options': [{'days': d, 'label': label} for d, label in WINDOW_OPTIONS],
        'a': left,
        'b': right,
        'leader': leader,
        'gap': abs(left['recent'] - right['recent']),
    }
