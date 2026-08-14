from datetime import datetime, timedelta, timezone
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from pydantic import BaseModel

from app.api.schemas import ConfigIn, ConfigOut, JobOut, RunOut, RunRequest
from app.db import get_db
from app.models import Company, ConsoleLog, JobMaster, ScrapeRun, SearchConfig
from app.tasks import _config_busy, run_scrape

router = APIRouter(prefix='/api')


# ---------- MNC watchlist (company-first collection, 2026-08-14) ----------

class WatchCompanyIn(BaseModel):
    name: str


@router.get('/watchlist/companies')
def list_watchlist_companies(db: Session = Depends(get_db)):
    """Full MNC roster (owner /companies): every company-scoped search with
    catch counts — most jobs first, never truncated."""
    from app.mnc_watchlist import watchlist_roster

    rows = watchlist_roster(db)
    return {'total': len(rows), 'companies': rows}


@router.post('/watchlist/companies', status_code=201)
def add_watchlist_company(payload: WatchCompanyIn, db: Session = Depends(get_db)):
    """Add a giant to the MNC watchlist: watched company + company-scoped
    fresher search + immediate first scrape. Idempotent by match needle."""
    from app.mnc_watchlist import add_watch_company, display_name

    cfg, created = add_watch_company(db, payload.name)
    if cfg is None:
        raise HTTPException(422, 'company name required')
    db.commit()
    db.refresh(cfg)
    first_scrape_queued = False
    if created and not _config_busy(db, cfg.id):
        run = ScrapeRun(
            search_config_id=cfg.id,
            run_type='one_off',
            target_date=datetime.now(timezone.utc).date(),
            status='dispatched',
        )
        db.add(run)
        db.commit()
        run_scrape.delay(run.id)
        first_scrape_queued = True
    return {
        'company': display_name(cfg.target_company or ''),
        'created': created,
        'search_name': cfg.name,
        'enabled': cfg.enabled,
        'first_scrape_queued': first_scrape_queued,
    }


# ---------- Tower data reset (base rebuild, 2026-08-14) ----------

@router.get('/tower/reset-preview')
def tower_reset_preview(db: Session = Depends(get_db)):
    from app.tower_reset import reset_preview

    return reset_preview(db)


@router.post('/tower/reset')
def tower_reset(db: Session = Depends(get_db)):
    from app.tower_reset import reset_tower_data

    return reset_tower_data(db)


# ---------- search configs ----------

@router.get('/configs', response_model=list[ConfigOut])
def list_configs(sector: str | None = None, db: Session = Depends(get_db)):
    from app.sectors import normalize_sector
    q = select(SearchConfig).order_by(SearchConfig.id)
    sector = normalize_sector(sector)
    if sector:
        q = q.where(SearchConfig.sector == sector)
    return db.execute(q).scalars().all()


@router.post('/configs', response_model=ConfigOut, status_code=201)
def create_config(payload: ConfigIn, db: Session = Depends(get_db)):
    cfg = SearchConfig(**payload.model_dump())
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


@router.put('/configs/{config_id}', response_model=ConfigOut)
def update_config(config_id: int, payload: ConfigIn, db: Session = Depends(get_db)):
    cfg = db.get(SearchConfig, config_id)
    if cfg is None:
        raise HTTPException(404, 'config not found')
    for key, value in payload.model_dump().items():
        setattr(cfg, key, value)
    db.commit()
    db.refresh(cfg)
    return cfg


@router.post('/configs/{config_id}/toggle', response_model=ConfigOut)
def toggle_config(config_id: int, db: Session = Depends(get_db)):
    cfg = db.get(SearchConfig, config_id)
    if cfg is None:
        raise HTTPException(404, 'config not found')
    cfg.enabled = not cfg.enabled
    db.commit()
    db.refresh(cfg)
    return cfg


# ---------- runs ----------

@router.post('/runs', response_model=RunOut, status_code=201)
def create_run(payload: RunRequest, db: Session = Depends(get_db)):
    cfg = db.get(SearchConfig, payload.search_config_id)
    if cfg is None:
        raise HTTPException(404, 'config not found')

    now = datetime.now(timezone.utc)
    immediate = payload.scheduled_for is None or payload.scheduled_for <= now

    if immediate and _config_busy(db, cfg.id):
        raise HTTPException(409, 'a run for this config is already dispatched/running')

    run = ScrapeRun(
        search_config_id=cfg.id,
        run_type='one_off',
        scheduled_for=payload.scheduled_for,
        target_date=(payload.scheduled_for or now).date(),
        status='dispatched' if immediate else 'queued',
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    if immediate:
        run_scrape.delay(run.id)
    return run


@router.post('/runs/{run_id}/cancel', response_model=RunOut)
def cancel_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(ScrapeRun, run_id)
    if run is None:
        raise HTTPException(404, 'run not found')
    if run.status in ('queued', 'dispatched'):
        run.status = 'cancelled'
    elif run.status == 'running':
        # Worker checks this flag before each page and stops gracefully
        run.status = 'cancel_requested'
    else:
        raise HTTPException(409, f'cannot cancel a run in status {run.status}')
    db.commit()
    db.refresh(run)
    return run


@router.get('/runs', response_model=list[RunOut])
def list_runs(
    limit: int = Query(50, le=500),
    status: str | None = None,
    db: Session = Depends(get_db),
):
    query = select(ScrapeRun).order_by(desc(ScrapeRun.id)).limit(limit)
    if status:
        query = query.where(ScrapeRun.status == status)
    return db.execute(query).scalars().all()


# ---------- jobs ----------

@router.get('/jobs', response_model=list[JobOut])
def list_jobs(
    limit: int = Query(100, le=1000),
    offset: int = 0,
    sector: str | None = None,
    city: str | None = None,
    experience: str | None = None,
    track: str | None = None,
    role_family: str | None = None,
    title_terms: str | None = None,
    company: str | None = None,
    title: str | None = None,
    posted_date: str | None = None,
    days: int | None = None,
    search_config_id: int | None = None,
    company_id: int | None = None,
    db: Session = Depends(get_db),
):
    from app.cities import normalize_city_filter
    from app.experience_bands import experience_clause, normalize_experience
    from app.job_role_families import ROLE_FAMILY_REGEX
    from app.sectors import normalize_sector
    from app.seniority import fresher_title_safe_clause

    sector = normalize_sector(sector)
    city = normalize_city_filter(city)
    experience = normalize_experience(experience)
    track = (track or '').strip().lower() or None
    if track not in (None, 'fresher', 'signal'):
        track = None
    role_family = role_family if role_family in ROLE_FAMILY_REGEX else None
    terms = [
        token for token in re.findall(r'[a-z0-9+#.-]+', (title_terms or '').lower())
        if len(token) >= 2
    ][:5]
    query = (
        select(JobMaster, Company.name)
        .outerjoin(Company, JobMaster.company_id == Company.id)
        .order_by(desc(JobMaster.scraped_at), desc(JobMaster.id))
        .limit(limit)
        .offset(offset)
    )
    if sector:
        query = query.where(JobMaster.sector == sector)
    if city:
        query = query.where(JobMaster.city_key == city)
    exp = experience_clause(experience)
    if exp is not None:
        query = query.where(exp)
    if track:
        query = query.where(JobMaster.source_track == track)
        if track == 'fresher' and exp is None:
            fresher_exp = experience_clause('fresher')
            query = query.where(or_(JobMaster.experience_band.is_(None), fresher_exp))
    if experience == 'fresher' or (track == 'fresher' and exp is None):
        # Fresher truthfulness (2026-08-14): a title carrying seniority
        # evidence (II/III, Senior, Lead, Manager...) can never ship to a
        # fresher, even while its band is unverified NULL — LinkedIn's
        # Entry tag alone is not proof. See app/seniority.py.
        query = query.where(fresher_title_safe_clause())
    if role_family:
        pattern = ROLE_FAMILY_REGEX[role_family].removeprefix('(?i)')
        query = query.where(JobMaster.title.op('~*')(pattern))
    if terms:
        query = query.where(or_(*[JobMaster.title.ilike(f'%{term}%') for term in terms]))
    if company:
        query = query.where(Company.name.ilike(f'%{company}%'))
    if title:
        query = query.where(JobMaster.title.ilike(f'%{title}%'))
    if posted_date:
        query = query.where(JobMaster.posted_date == posted_date)
    if days in (0, 1, 2, 4, 7, 14, 30):
        # Same window convention as /api/jobs/insights: 0 = rolling 24 hours
        # by catch time (scraped_at); any other value = LinkedIn's own
        # posted_date over the last N calendar days.
        now = datetime.now(timezone.utc)
        if days == 0:
            query = query.where(JobMaster.scraped_at >= now - timedelta(hours=24))
        else:
            today = now.date()
            query = query.where(
                JobMaster.posted_date >= today - timedelta(days=days - 1),
                JobMaster.posted_date < today + timedelta(days=1),
            )
    if search_config_id:
        query = query.where(JobMaster.search_config_id == search_config_id)
    if company_id:
        query = query.where(JobMaster.company_id == company_id)

    rows = db.execute(query).all()
    out = []
    for job, company_name in rows:
        # Don't model_validate(job) — relationship `company` is a Company object
        out.append(JobOut(
            id=job.id,
            linkedin_job_id=job.linkedin_job_id,
            title=job.title,
            company=company_name,
            location=job.location,
            city_key=job.city_key,
            sector=job.sector,
            experience_band=job.experience_band,
            source_track=job.source_track,
            job_url=job.job_url,
            posted_date=job.posted_date,
            scraped_at=job.scraped_at,
        ))
    return out


@router.get('/jobs/insights')
def job_insights(
    days: int = 7,
    city: str | None = None,
    experience: str | None = None,
    track: str | None = None,
    role_family: str | None = None,
    title_terms: str | None = None,
    db: Session = Depends(get_db),
):
    """Grounded count/ranking primitive for JobMaster market questions."""
    from app.cities import city_label, normalize_city_filter
    from app.experience_bands import experience_clause, normalize_experience
    from app.job_role_families import ROLE_FAMILY_REGEX
    from app.seniority import fresher_title_safe_clause

    days = days if days in (0, 1, 2, 4, 7, 14, 30) else 7
    city = normalize_city_filter(city)
    experience = normalize_experience(experience)
    track = (track or '').strip().lower() or None
    if track not in (None, 'fresher', 'signal'):
        track = None
    role_family = role_family if role_family in ROLE_FAMILY_REGEX else None
    terms = [
        token for token in re.findall(r'[a-z0-9+#.-]+', (title_terms or '').lower())
        if len(token) >= 2
    ][:5]

    now = datetime.now(timezone.utc)
    today = now.date()
    if days == 0:
        time_col = JobMaster.scraped_at
        recent_start = now - timedelta(hours=24)
        recent_end = now
        prior_start = recent_start - timedelta(days=1)
        prior_end = recent_start
    else:
        time_col = JobMaster.posted_date
        recent_start = today - timedelta(days=days - 1)
        recent_end = today + timedelta(days=1)
        prior_start = recent_start - timedelta(days=days)
        prior_end = recent_start

    filters = []
    if city:
        filters.append(JobMaster.city_key == city)
    exp = experience_clause(experience)
    if exp is not None:
        filters.append(exp)
    if track:
        filters.append(JobMaster.source_track == track)
        if track == 'fresher' and exp is None:
            fresher_exp = experience_clause('fresher')
            filters.append(or_(JobMaster.experience_band.is_(None), fresher_exp))
    if experience == 'fresher' or (track == 'fresher' and exp is None):
        # Fresher truthfulness: counts must match what fresher searches
        # actually show — seniority-titled rows are excluded from both.
        filters.append(fresher_title_safe_clause())
    if role_family:
        pattern = ROLE_FAMILY_REGEX[role_family].removeprefix('(?i)')
        filters.append(JobMaster.title.op('~*')(pattern))
    if terms:
        filters.append(or_(*[JobMaster.title.ilike(f'%{term}%') for term in terms]))

    def with_filters(query, start, end):
        return query.where(time_col >= start, time_col < end, *filters)

    total_query = (
        select(func.count(JobMaster.id))
        .outerjoin(SearchConfig, JobMaster.search_config_id == SearchConfig.id)
    )
    total = int(db.execute(with_filters(total_query, recent_start, recent_end)).scalar() or 0)
    prior = int(db.execute(with_filters(total_query, prior_start, prior_end)).scalar() or 0)

    companies_query = (
        select(Company.name, func.count(JobMaster.id).label('n'))
        .join(JobMaster, JobMaster.company_id == Company.id)
        .outerjoin(SearchConfig, JobMaster.search_config_id == SearchConfig.id)
        .group_by(Company.id, Company.name)
        .order_by(desc('n'))
        .limit(10)
    )
    companies = db.execute(
        with_filters(companies_query, recent_start, recent_end)
    ).all()

    cities_query = (
        select(JobMaster.city_key, func.count(JobMaster.id).label('n'))
        .outerjoin(SearchConfig, JobMaster.search_config_id == SearchConfig.id)
        .where(JobMaster.city_key.is_not(None))
        .group_by(JobMaster.city_key)
        .order_by(desc('n'))
        .limit(20)
    )
    cities = db.execute(with_filters(cities_query, recent_start, recent_end)).all()
    roles_query = (
        select(SearchConfig.name, func.count(JobMaster.id).label('n'))
        .join(JobMaster, JobMaster.search_config_id == SearchConfig.id)
        .group_by(SearchConfig.id, SearchConfig.name)
        .order_by(desc('n'))
        .limit(10)
    )
    roles = db.execute(with_filters(roles_query, recent_start, recent_end)).all()
    return {
        'days': days,
        'city': city or '',
        'role_family': role_family or '',
        'experience': experience or '',
        'track': track or '',
        'total': total,
        'prior_total': prior,
        'delta': total - prior,
        'companies': [{'name': name, 'n': int(n or 0)} for name, n in companies],
        'cities': [
            {'city': key, 'label': city_label(key), 'n': int(n or 0)}
            for key, n in cities
        ],
        'roles': [{'name': name, 'n': int(n or 0)} for name, n in roles],
    }


# ---------- console ----------

@router.get('/console')
def console_feed(
    after_id: int = 0,
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_db),
):
    if after_id:
        rows = db.execute(
            select(ConsoleLog).where(ConsoleLog.id > after_id)
            .order_by(ConsoleLog.id).limit(limit)
        ).scalars().all()
    else:
        rows = db.execute(
            select(ConsoleLog).order_by(desc(ConsoleLog.id)).limit(limit)
        ).scalars().all()[::-1]
    return [{
        'id': r.id, 'ts': r.ts, 'source': r.source, 'level': r.level,
        'run_id': r.run_id, 'message': r.message,
    } for r in rows]


# ---------- stats ----------

@router.get('/stats')
def stats(db: Session = Depends(get_db)):
    today = datetime.now(timezone.utc).date()
    return {
        'total_jobs': db.execute(select(func.count(JobMaster.id))).scalar(),
        'jobs_today': db.execute(
            select(func.count(JobMaster.id)).where(func.date(JobMaster.scraped_at) == today)
        ).scalar(),
        'total_companies': db.execute(select(func.count(Company.id))).scalar(),
        'configs_enabled': db.execute(
            select(func.count(SearchConfig.id)).where(SearchConfig.enabled.is_(True))
        ).scalar(),
        'runs_active': db.execute(
            select(func.count(ScrapeRun.id)).where(
                ScrapeRun.status.in_(('queued', 'dispatched', 'running'))
            )
        ).scalar(),
        'runs_failed_24h': db.execute(
            select(func.count(ScrapeRun.id)).where(
                ScrapeRun.status == 'failed',
                ScrapeRun.created_at >= datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                ),
            )
        ).scalar(),
    }


# ---------- deploy verification ----------

@router.get('/deploy/status')
def deploy_status():
    """No-DB, no-auth stamp so a PR merge can be confirmed live on the
    ThinkPad: compares the last `Deploy ThinkPad` run's commit against the
    commit the running process was actually started from.
    See documents/deploy-verification.md."""
    from app.deploy_status import compute_deploy_status
    return compute_deploy_status()


# ---------- telegram guest access ----------

@router.get('/telegram/guests')
def telegram_guests():
    """Read-only view of who currently has Telegram bot access: temporary
    numeric-id guests (granted via /allow) and allowed @usernames (default
    or granted via /allowuser). Mutations stay Telegram-only — see
    documents/hermes-agent-integration.md "Telegram guest access"."""
    from app.telegram_guests import list_guests, list_usernames
    return {'guests': list_guests(), 'usernames': list_usernames()}
