"""Hiring Signals — derived intelligence from tracked openings.

Pure read-side helpers. No jargon in returned labels; UI stays human.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, JobMaster, SearchConfig

# 0 = rolling last 24h (scraped_at). 1+ = calendar days inclusive (posted_date).
WINDOW_OPTIONS = (
    (0, 'Last 24 hours'),
    (1, 'Today'),
    (2, 'Last 2 days'),
    (4, 'Last 4 days'),
    (7, 'Last 7 days'),
    (14, 'Last 14 days'),
    (30, 'Last 30 days'),
)
ALLOWED_WINDOWS = {d for d, _ in WINDOW_OPTIONS}


@dataclass
class DayPoint:
    day: date
    n: int


@dataclass
class RoleSignal:
    search_id: int
    name: str
    keywords: str
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


@dataclass
class CompanySignal:
    company_id: int
    name: str
    recent: int
    prior: int
    watched: bool = False
    logo_url: str | None = None
    punchline: str | None = None
    tagline: str | None = None
    follower_count: int | None = None
    employee_count_label: str | None = None

    @property
    def delta(self) -> int:
        return self.recent - self.prior

    @property
    def delta_pct(self) -> float | None:
        if self.prior <= 0:
            return None if self.recent <= 0 else 100.0
        return (self.recent - self.prior) / self.prior * 100.0


@dataclass
class HiringSignals:
    window_days: int
    today: date
    recent_total: int
    prior_total: int
    daily: list[DayPoint]
    daily_max: int
    growing_roles: list[RoleSignal]
    slowing_roles: list[RoleSignal]
    fastest_companies: list[CompanySignal]
    headline: str

    @property
    def delta(self) -> int:
        return self.recent_total - self.prior_total

    @property
    def delta_pct(self) -> float | None:
        if self.prior_total <= 0:
            return None if self.recent_total <= 0 else 100.0
        return (self.recent_total - self.prior_total) / self.prior_total * 100.0

    @property
    def role_recent_max(self) -> int:
        return max([r.recent for r in self.growing_roles] + [1])

    @property
    def company_recent_max(self) -> int:
        return max([c.recent for c in self.fastest_companies] + [1])


def _count_jobs(db: Session, start: date | datetime, end: date | datetime,
                search_id: int | None = None,
                company_id: int | None = None,
                sector: str | None = None,
                city: str | None = None,
                experience: str | None = None,
                *,
                by_scraped: bool = False) -> int:
    """Count jobs in [start, end). Uses posted_date or scraped_at."""
    from app.experience_bands import experience_clause

    if by_scraped:
        q = select(func.count(JobMaster.id)).where(
            JobMaster.scraped_at >= start,
            JobMaster.scraped_at < end,
        )
    else:
        q = select(func.count(JobMaster.id)).where(
            JobMaster.posted_date >= start,
            JobMaster.posted_date < end,
        )
    if search_id:
        q = q.where(JobMaster.search_config_id == search_id)
    if company_id:
        q = q.where(JobMaster.company_id == company_id)
    if sector:
        q = q.where(JobMaster.sector == sector)
    if city:
        q = q.where(JobMaster.city_key == city)
    exp = experience_clause(experience)
    if exp is not None:
        q = q.where(exp)
    return db.execute(q).scalar() or 0


def _window_bounds(
    window_days: int,
) -> tuple[int, date | datetime, date | datetime, date | datetime, date | datetime, bool]:
    """Return (days, recent_start, recent_end, prior_start, prior_end, by_scraped)."""
    if window_days not in ALLOWED_WINDOWS:
        window_days = 7
    if window_days == 0:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=24)
        prior_end = start
        prior_start = prior_end - timedelta(hours=24)
        return window_days, start, end, prior_start, prior_end, True
    today = date.today()
    # Recent = last N calendar days including today; prior = the N days before that
    recent_start = today - timedelta(days=window_days - 1)
    prior_start = recent_start - timedelta(days=window_days)
    recent_end = today + timedelta(days=1)  # exclusive
    prior_end = recent_start
    return window_days, recent_start, recent_end, prior_start, prior_end, False


def _window_labels(window_days: int) -> tuple[str, str]:
    if window_days == 0:
        return 'last 24 hours', 'prior 24 hours'
    if window_days == 1:
        return 'today', 'yesterday'
    return f'last {window_days} days', f'prior {window_days} days'


def compute_hiring_signals(
    db: Session,
    window_days: int = 7,
    sector: str | None = None,
    city: str | None = None,
    experience: str | None = None,
) -> HiringSignals:
    from app.experience_bands import normalize_experience

    experience = normalize_experience(experience)
    (window_days, recent_start, recent_end, prior_start, prior_end,
     by_scraped) = _window_bounds(window_days)
    today = date.today()

    recent_total = _count_jobs(
        db, recent_start, recent_end, sector=sector, city=city,
        experience=experience, by_scraped=by_scraped,
    )
    prior_total = _count_jobs(
        db, prior_start, prior_end, sector=sector, city=city,
        experience=experience, by_scraped=by_scraped,
    )

    # Daily series spanning recent window (for sparkline)
    if by_scraped:
        daily = [DayPoint(day=today, n=recent_total)]
    else:
        assert isinstance(recent_start, date) and isinstance(recent_end, date)
        dq = (
            select(JobMaster.posted_date, func.count(JobMaster.id))
            .where(
                JobMaster.posted_date >= recent_start,
                JobMaster.posted_date < recent_end,
            )
            .group_by(JobMaster.posted_date)
        )
        if sector:
            dq = dq.where(JobMaster.sector == sector)
        if city:
            dq = dq.where(JobMaster.city_key == city)
        from app.experience_bands import experience_clause
        exp_c = experience_clause(experience)
        if exp_c is not None:
            dq = dq.where(exp_c)
        daily_map = dict(db.execute(dq).all())
        daily = [
            DayPoint(day=recent_start + timedelta(days=i),
                     n=daily_map.get(recent_start + timedelta(days=i), 0))
            for i in range(window_days)
        ]
    daily_max = max([d.n for d in daily] + [1])

    roles: list[RoleSignal] = []
    cfg_q = select(SearchConfig).order_by(SearchConfig.name)
    if sector:
        cfg_q = cfg_q.where(SearchConfig.sector == sector)
    for cfg in db.execute(cfg_q).scalars():
        roles.append(RoleSignal(
            search_id=cfg.id,
            name=cfg.name,
            keywords=cfg.keywords,
            recent=_count_jobs(
                db, recent_start, recent_end, search_id=cfg.id,
                sector=sector, city=city, experience=experience,
                by_scraped=by_scraped,
            ),
            prior=_count_jobs(
                db, prior_start, prior_end, search_id=cfg.id,
                sector=sector, city=city, experience=experience,
                by_scraped=by_scraped,
            ),
        ))
    growing_roles = sorted(
        [r for r in roles if r.recent > 0 or r.prior > 0],
        key=lambda r: (r.delta, r.recent),
        reverse=True,
    )
    slowing_roles = sorted(
        [r for r in roles if r.delta < 0],
        key=lambda r: (r.delta, -r.recent),
    )

    # Company velocity: top by recent openings, with prior for delta
    time_col = JobMaster.scraped_at if by_scraped else JobMaster.posted_date
    co_q = (
        select(
            Company.id, Company.name, Company.watched,
            func.count(JobMaster.id).label('n'),
        )
        .join(JobMaster, JobMaster.company_id == Company.id)
        .where(time_col >= recent_start, time_col < recent_end)
        .group_by(Company.id, Company.name, Company.watched)
        .order_by(func.count(JobMaster.id).desc())
        .limit(40)
    )
    if sector:
        co_q = co_q.where(JobMaster.sector == sector)
    if city:
        co_q = co_q.where(JobMaster.city_key == city)
    from app.experience_bands import experience_clause as _exp_clause
    _exp = _exp_clause(experience)
    if _exp is not None:
        co_q = co_q.where(_exp)
    recent_by_co = db.execute(co_q).all()
    fastest: list[CompanySignal] = []
    for cid, name, watched, recent_n in recent_by_co:
        prior_n = _count_jobs(
            db, prior_start, prior_end, company_id=cid,
            sector=sector, city=city, experience=experience,
            by_scraped=by_scraped,
        )
        fastest.append(CompanySignal(
            company_id=cid, name=name, recent=recent_n, prior=prior_n,
            watched=bool(watched),
        ))
    # Rank by velocity (recent) then by growth
    fastest.sort(key=lambda c: (c.recent, c.delta), reverse=True)

    # Headline: one sentence insight
    win_label, prior_label = _window_labels(window_days)
    if recent_total == 0 and prior_total == 0:
        headline = 'No openings in this window yet — run a search to light up the signals.'
    elif prior_total == 0:
        headline = (
            f'{recent_total} opening{"s" if recent_total != 1 else ""} {win_label} '
            f'— first signal window for this tower.'
        )
    else:
        direction = 'up' if recent_total > prior_total else (
            'down' if recent_total < prior_total else 'flat'
        )
        pct = abs(recent_total - prior_total) / prior_total * 100
        if direction == 'flat':
            headline = (
                f'Openings are steady: {recent_total} {win_label}, '
                f'same pace as {prior_label}.'
            )
        else:
            headline = (
                f'Openings are {direction} {pct:.0f}% vs {prior_label} '
                f'({recent_total} now vs {prior_total} before).'
            )
        if growing_roles and growing_roles[0].delta > 0:
            top = growing_roles[0]
            headline += f' Fastest role rise: {top.name} (+{top.delta}).'
        if fastest:
            headline += f' Top hiring pace: {fastest[0].name} ({fastest[0].recent}).'

    return HiringSignals(
        window_days=window_days,
        today=today,
        recent_total=recent_total,
        prior_total=prior_total,
        daily=daily,
        daily_max=daily_max,
        growing_roles=growing_roles,
        slowing_roles=slowing_roles[:5],
        fastest_companies=fastest,
        headline=headline,
    )


def format_delta(n: int) -> str:
    if n > 0:
        return f'+{n}'
    return str(n)


def format_pct(pct: float | None) -> str:
    if pct is None:
        return 'new'
    sign = '+' if pct > 0 else ''
    return f'{sign}{pct:.0f}%'


def set_watched(db: Session, company_id: int, watched: bool) -> Company | None:
    company = db.get(Company, company_id)
    if company is None:
        return None
    company.watched = watched
    company.watched_at = datetime.now(timezone.utc) if watched else None
    db.commit()
    return company


def ensure_starter_watchlist(db: Session, limit: int = 10) -> int:
    """If nobody is watched yet, pin the current fastest hirers so the page isn't empty."""
    any_watched = db.execute(
        select(Company.id).where(Company.watched.is_(True)).limit(1)
    ).scalar_one_or_none()
    if any_watched is not None:
        return 0
    signals = compute_hiring_signals(db, window_days=7)
    pinned = 0
    now = datetime.now(timezone.utc)
    for co in signals.fastest_companies[:limit]:
        company = db.get(Company, co.company_id)
        if company is None:
            continue
        company.watched = True
        company.watched_at = now
        pinned += 1
    if pinned:
        db.commit()
    return pinned


def companies_for_role(
    db: Session,
    search_id: int,
    window_days: int = 7,
    limit: int = 40,
    city: str | None = None,
    sector: str | None = None,
    experience: str | None = None,
) -> tuple[str, list[CompanySignal]]:
    """Companies hiring for a search role, ranked max → min in the window."""
    from app.experience_bands import experience_clause, normalize_experience

    experience = normalize_experience(experience)
    (window_days, recent_start, recent_end, prior_start, prior_end,
     by_scraped) = _window_bounds(window_days)
    cfg = db.get(SearchConfig, search_id)
    role_name = cfg.name if cfg else f'Role {search_id}'
    time_col = JobMaster.scraped_at if by_scraped else JobMaster.posted_date
    q = (
        select(
            Company.id, Company.name, Company.watched,
            func.count(JobMaster.id).label('n'),
        )
        .join(JobMaster, JobMaster.company_id == Company.id)
        .where(
            JobMaster.search_config_id == search_id,
            time_col >= recent_start,
            time_col < recent_end,
        )
        .group_by(Company.id, Company.name, Company.watched)
        .order_by(func.count(JobMaster.id).desc())
        .limit(limit)
    )
    if city:
        q = q.where(JobMaster.city_key == city)
    if sector:
        q = q.where(JobMaster.sector == sector)
    exp = experience_clause(experience)
    if exp is not None:
        q = q.where(exp)
    rows = db.execute(q).all()
    out: list[CompanySignal] = []
    for cid, name, watched, recent_n in rows:
        prior_n = _count_jobs(
            db, prior_start, prior_end,
            search_id=search_id, company_id=cid,
            city=city, sector=sector, experience=experience,
            by_scraped=by_scraped,
        )
        out.append(CompanySignal(
            company_id=cid, name=name, recent=recent_n, prior=prior_n,
            watched=bool(watched),
        ))
    return role_name, out


def cities_for_role(
    db: Session,
    search_id: int,
    window_days: int = 7,
    sector: str | None = None,
    experience: str | None = None,
) -> list[dict]:
    """City breakdown for a role in the window — max → min."""
    from app.cities import city_label
    from app.experience_bands import experience_clause, normalize_experience

    experience = normalize_experience(experience)
    (window_days, recent_start, recent_end, _ps, _pe,
     by_scraped) = _window_bounds(window_days)
    time_col = JobMaster.scraped_at if by_scraped else JobMaster.posted_date
    q = (
        select(JobMaster.city_key, func.count(JobMaster.id).label('n'))
        .where(
            JobMaster.search_config_id == search_id,
            time_col >= recent_start,
            time_col < recent_end,
            JobMaster.city_key.is_not(None),
        )
        .group_by(JobMaster.city_key)
        .order_by(func.count(JobMaster.id).desc())
    )
    if sector:
        q = q.where(JobMaster.sector == sector)
    exp = experience_clause(experience)
    if exp is not None:
        q = q.where(exp)
    rows = db.execute(q).all()
    return [
        {
            'city': key or 'other',
            'label': city_label(key or 'other'),
            'n': int(n or 0),
        }
        for key, n in rows
    ]


def watchlist_rows(
    db: Session,
    window_days: int = 7,
    q: str = '',
    sector: str | None = None,
    city: str | None = None,
    experience: str | None = None,
) -> list[CompanySignal]:
    """Watched companies with velocity; optional name / sector / city / experience."""
    from app.experience_bands import normalize_experience

    experience = normalize_experience(experience)
    ensure_starter_watchlist(db)
    (window_days, recent_start, recent_end, prior_start, prior_end,
     by_scraped) = _window_bounds(window_days)

    query = select(Company).where(Company.watched.is_(True))
    if q.strip():
        query = query.where(Company.name.ilike(f'%{q.strip()}%'))
    query = query.order_by(Company.name)
    companies = db.execute(query).scalars().all()

    rows: list[CompanySignal] = []
    for company in companies:
        recent = _count_jobs(
            db, recent_start, recent_end, company_id=company.id,
            sector=sector, city=city, experience=experience,
            by_scraped=by_scraped,
        )
        prior = _count_jobs(
            db, prior_start, prior_end, company_id=company.id,
            sector=sector, city=city, experience=experience,
            by_scraped=by_scraped,
        )
        rows.append(CompanySignal(
            company_id=company.id,
            name=company.name,
            recent=recent,
            prior=prior,
            watched=True,
            logo_url=company.logo_url,
            punchline=company.punchline,
            tagline=company.tagline,
            follower_count=company.follower_count,
            employee_count_label=company.employee_count_label,
        ))
    rows.sort(key=lambda c: (c.recent, c.delta), reverse=True)
    return rows


def company_directory(db: Session, q: str = '', limit: int = 40) -> list[CompanySignal]:
    """Searchable company list for adding to the watchlist."""
    today = date.today()
    recent_start = today - timedelta(days=6)
    recent_end = today + timedelta(days=1)
    prior_start = recent_start - timedelta(days=7)

    query = (
        select(Company)
        .order_by(Company.name.asc())
        .limit(limit * 3)
    )
    if q.strip():
        query = query.where(Company.name.ilike(f'%{q.strip()}%'))

    rows: list[CompanySignal] = []
    for company in db.execute(query).scalars().all():
        recent = _count_jobs(db, recent_start, recent_end, company_id=company.id)
        prior = _count_jobs(db, prior_start, recent_start, company_id=company.id)
        rows.append(CompanySignal(
            company_id=company.id,
            name=company.name,
            recent=recent,
            prior=prior,
            watched=bool(company.watched),
            logo_url=company.logo_url,
            punchline=company.punchline,
            tagline=company.tagline,
            follower_count=company.follower_count,
            employee_count_label=company.employee_count_label,
        ))
    rows.sort(key=lambda c: (c.recent, c.name.lower()), reverse=True)
    return rows[:limit]
