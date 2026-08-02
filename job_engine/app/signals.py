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
                *,
                by_scraped: bool = False) -> int:
    """Count jobs in [start, end). Uses posted_date or scraped_at."""
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


def compute_hiring_signals(db: Session, window_days: int = 7) -> HiringSignals:
    (window_days, recent_start, recent_end, prior_start, prior_end,
     by_scraped) = _window_bounds(window_days)
    today = date.today()

    recent_total = _count_jobs(
        db, recent_start, recent_end, by_scraped=by_scraped,
    )
    prior_total = _count_jobs(
        db, prior_start, prior_end, by_scraped=by_scraped,
    )

    # Daily series spanning recent window (for sparkline)
    if by_scraped:
        daily = [DayPoint(day=today, n=recent_total)]
    else:
        assert isinstance(recent_start, date) and isinstance(recent_end, date)
        daily_map = dict(db.execute(
            select(JobMaster.posted_date, func.count(JobMaster.id))
            .where(
                JobMaster.posted_date >= recent_start,
                JobMaster.posted_date < recent_end,
            )
            .group_by(JobMaster.posted_date)
        ).all())
        daily = [
            DayPoint(day=recent_start + timedelta(days=i),
                     n=daily_map.get(recent_start + timedelta(days=i), 0))
            for i in range(window_days)
        ]
    daily_max = max([d.n for d in daily] + [1])

    roles: list[RoleSignal] = []
    for cfg in db.execute(select(SearchConfig).order_by(SearchConfig.name)).scalars():
        roles.append(RoleSignal(
            search_id=cfg.id,
            name=cfg.name,
            keywords=cfg.keywords,
            recent=_count_jobs(
                db, recent_start, recent_end, search_id=cfg.id, by_scraped=by_scraped,
            ),
            prior=_count_jobs(
                db, prior_start, prior_end, search_id=cfg.id, by_scraped=by_scraped,
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
    if by_scraped:
        recent_by_co = db.execute(
            select(
                Company.id, Company.name, Company.watched,
                func.count(JobMaster.id).label('n'),
            )
            .join(JobMaster, JobMaster.company_id == Company.id)
            .where(
                JobMaster.scraped_at >= recent_start,
                JobMaster.scraped_at < recent_end,
            )
            .group_by(Company.id, Company.name, Company.watched)
            .order_by(func.count(JobMaster.id).desc())
            .limit(40)
        ).all()
    else:
        recent_by_co = db.execute(
            select(
                Company.id, Company.name, Company.watched,
                func.count(JobMaster.id).label('n'),
            )
            .join(JobMaster, JobMaster.company_id == Company.id)
            .where(
                JobMaster.posted_date >= recent_start,
                JobMaster.posted_date < recent_end,
            )
            .group_by(Company.id, Company.name, Company.watched)
            .order_by(func.count(JobMaster.id).desc())
            .limit(40)
        ).all()
    fastest: list[CompanySignal] = []
    for cid, name, watched, recent_n in recent_by_co:
        prior_n = _count_jobs(
            db, prior_start, prior_end, company_id=cid, by_scraped=by_scraped,
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
    db: Session, search_id: int, window_days: int = 7, limit: int = 40,
) -> tuple[str, list[CompanySignal]]:
    """Companies hiring for a search role, ranked max → min in the window."""
    (window_days, recent_start, recent_end, prior_start, prior_end,
     by_scraped) = _window_bounds(window_days)
    cfg = db.get(SearchConfig, search_id)
    role_name = cfg.name if cfg else f'Role {search_id}'
    time_col = JobMaster.scraped_at if by_scraped else JobMaster.posted_date
    rows = db.execute(
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
    ).all()
    out: list[CompanySignal] = []
    for cid, name, watched, recent_n in rows:
        prior_n = _count_jobs(
            db, prior_start, prior_end,
            search_id=search_id, company_id=cid, by_scraped=by_scraped,
        )
        out.append(CompanySignal(
            company_id=cid, name=name, recent=recent_n, prior=prior_n,
            watched=bool(watched),
        ))
    return role_name, out


def watchlist_rows(db: Session, window_days: int = 7, q: str = '') -> list[CompanySignal]:
    """Watched companies with velocity; optional name filter."""
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
            db, recent_start, recent_end, company_id=company.id, by_scraped=by_scraped,
        )
        prior = _count_jobs(
            db, prior_start, prior_end, company_id=company.id, by_scraped=by_scraped,
        )
        rows.append(CompanySignal(
            company_id=company.id,
            name=company.name,
            recent=recent,
            prior=prior,
            watched=True,
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
        select(
            Company.id, Company.name, Company.watched,
            func.count(JobMaster.id).label('n'),
        )
        .outerjoin(JobMaster, JobMaster.company_id == Company.id)
        .group_by(Company.id, Company.name, Company.watched)
        .order_by(func.count(JobMaster.id).desc(), Company.name.asc())
        .limit(limit)
    )
    if q.strip():
        query = query.where(Company.name.ilike(f'%{q.strip()}%'))

    rows: list[CompanySignal] = []
    for cid, name, watched, recent_n in db.execute(query).all():
        # recent_n here is all-time join count when no date filter — refine:
        recent = _count_jobs(db, recent_start, recent_end, company_id=cid)
        prior = _count_jobs(db, prior_start, recent_start, company_id=cid)
        rows.append(CompanySignal(
            company_id=cid, name=name, recent=recent, prior=prior,
            watched=bool(watched),
        ))
    rows.sort(key=lambda c: (c.recent, c.name.lower()), reverse=True)
    return rows
