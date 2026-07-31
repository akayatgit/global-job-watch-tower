from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.schemas import ConfigIn, ConfigOut, JobOut, RunOut, RunRequest
from app.db import get_db
from app.models import Company, ConsoleLog, JobMaster, ScrapeRun, SearchConfig
from app.tasks import _config_busy, run_scrape

router = APIRouter(prefix='/api')


# ---------- search configs ----------

@router.get('/configs', response_model=list[ConfigOut])
def list_configs(db: Session = Depends(get_db)):
    return db.execute(select(SearchConfig).order_by(SearchConfig.id)).scalars().all()


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
    company: str | None = None,
    title: str | None = None,
    posted_date: str | None = None,
    db: Session = Depends(get_db),
):
    query = (
        select(JobMaster, Company.name)
        .outerjoin(Company, JobMaster.company_id == Company.id)
        .order_by(desc(JobMaster.scraped_at))
        .limit(limit)
        .offset(offset)
    )
    if sector:
        query = query.where(JobMaster.sector == sector)
    if company:
        query = query.where(Company.name.ilike(f'%{company}%'))
    if title:
        query = query.where(JobMaster.title.ilike(f'%{title}%'))
    if posted_date:
        query = query.where(JobMaster.posted_date == posted_date)

    rows = db.execute(query).all()
    out = []
    for job, company_name in rows:
        item = JobOut.model_validate(job)
        item.company = company_name
        out.append(item)
    return out


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
