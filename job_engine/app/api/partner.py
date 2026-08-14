"""AvatarPitch partner API — /api/partner/v1/ (contract 2026-08-14).

Ashok's ruling: partners get a tower-owned API, never a database
connection — "all thinking here." Every ranking, freshness, skill-matching,
and one-per-company decision lives in this module, so it can improve
without any change on the consumer's side.

Contract: documents/avatarpitch-integration-plan.md. Breaking changes ship
as /api/partner/v2/, never as silent edits to v1.

Auth: static bearer token (PARTNER_API_TOKEN in job_engine/.env). Token
unset = the whole surface answers 503 (disabled), wrong/missing token =
401. Job rows are verbatim tower facts — no model authors anything here.
"""

from __future__ import annotations

import hmac
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app import config
from app.db import get_db
from app.experience_bands import (
    VALID_EXPERIENCE_IDS,
    experience_clause,
    normalize_experience,
)
from app.models import Company, JobMaster

# Cap on rows scanned before one-per-company dedupe — a reel needs ≤50
# cards, so scanning more than this is waste even on a huge fresh window.
MAX_SCAN_ROWS = 500
# Cap on rows scanned for reel-suggestions text matching.
MAX_SUGGESTION_ROWS = 5000

# Curated skill themes for reel-suggestions (fresher-lens tech skills).
# When a real skills-extraction column lands, this matching upgrades
# tower-side with zero client change.
SUGGESTION_SKILLS: tuple[str, ...] = (
    'sql', 'python', 'java', 'javascript', 'typescript', 'react', 'node',
    'angular', 'html', 'css', 'excel', 'power bi', 'tableau', 'aws',
    'azure', 'gcp', 'devops', 'docker', 'kubernetes', 'linux',
    'machine learning', 'data analysis', 'data science', 'testing',
    'selenium', 'automation', 'c++', 'c#', '.net', 'php', 'django',
    'spring', 'flutter', 'android', 'ios', 'cybersecurity', 'networking',
    'salesforce', 'sap',
)

router = APIRouter(prefix='/api/partner/v1')


# ---------- auth ----------

def require_partner_token(authorization: str | None = Header(default=None)) -> None:
    token = (getattr(config, 'PARTNER_API_TOKEN', '') or '').strip()
    if not token:
        raise HTTPException(503, 'partner API disabled — PARTNER_API_TOKEN not set')
    supplied = ''
    if authorization and authorization.lower().startswith('bearer '):
        supplied = authorization[7:].strip()
    if not supplied or not hmac.compare_digest(supplied, token):
        raise HTTPException(401, 'invalid or missing bearer token')


# ---------- response shapes (the contract) ----------

class PartnerJob(BaseModel):
    id: str
    company_name: str | None
    company_logo_url: str | None
    role_title: str
    experience_min_months: int | None
    experience_max_months: int | None
    experience_text: str | None
    experience_band: str | None
    education: list = []
    certifications: list = []
    domains: list = []
    location: str | None
    city: str | None
    apply_url: str
    source: str = 'linkedin'
    track: str | None
    posted_at: date | None
    scraped_at: datetime


class JobsResponse(BaseModel):
    jobs: list[PartnerJob]
    total_matched: int
    generated_at: datetime


class ReelSuggestion(BaseModel):
    skill: str
    active_jobs: int
    companies_with_logo: int


class SuggestionsResponse(BaseModel):
    suggestions: list[ReelSuggestion]
    generated_at: datetime


class PartnerHealth(BaseModel):
    ok: bool
    jobs_total: int
    freshest_scrape_at: datetime | None


# ---------- shared query pieces ----------

def _months(years: float | None) -> int | None:
    if years is None:
        return None
    return int(round(years * 12))


def _freshness_clause(fresh_days: int):
    """Fresh = posted within N days; jobs with no posted date fall back to
    catch time (fresher-track scrapes run daily past-24h windows, so a
    recent catch of a date-silent card is still a fresh posting)."""
    now = datetime.now(timezone.utc)
    cutoff_date = now.date() - timedelta(days=fresh_days)
    cutoff_ts = now - timedelta(days=fresh_days)
    return or_(
        JobMaster.posted_date >= cutoff_date,
        and_(JobMaster.posted_date.is_(None), JobMaster.scraped_at >= cutoff_ts),
    )


def _skill_clause(skill: str):
    needle = f'%{skill.strip()}%'
    return or_(
        JobMaster.title.ilike(needle),
        JobMaster.description_text.ilike(needle),
    )


def _job_filters(
    *,
    skill: str | None,
    experience: str | None,
    city: str | None,
    fresh_days: int,
    require_logo: bool,
) -> list:
    clauses = [_freshness_clause(fresh_days)]
    if skill:
        clauses.append(_skill_clause(skill))
    if experience:
        clause = experience_clause(experience)
        if clause is not None:
            clauses.append(clause)
    if city:
        clauses.append(JobMaster.city_key == city.strip().lower())
    if require_logo:
        clauses.append(Company.logo_url.is_not(None))
    return clauses


def _serialize(job: JobMaster, company: Company | None) -> PartnerJob:
    return PartnerJob(
        id=job.linkedin_job_id,
        company_name=company.name if company else None,
        company_logo_url=company.logo_url if company else None,
        role_title=job.title,
        experience_min_months=_months(job.experience_min_years),
        experience_max_months=_months(job.experience_max_years),
        experience_text=job.experience_label,
        experience_band=job.experience_band,
        education=list(job.degrees or []),
        certifications=list(job.certifications or []),
        domains=list(job.domains or []),
        location=job.location,
        city=job.city_key,
        apply_url=job.job_url,
        track=job.source_track,
        posted_at=job.posted_date,
        scraped_at=job.scraped_at,
    )


def query_partner_jobs(
    db: Session,
    *,
    skill: str | None = None,
    experience: str | None = None,
    city: str | None = None,
    fresh_days: int = 7,
    require_logo: bool = True,
    one_per_company: bool = True,
    limit: int = 6,
) -> tuple[list[PartnerJob], int]:
    """All the thinking: filter, rank freshest-first, dedupe to one card
    per company. Returns (jobs, total_matched_before_dedupe)."""
    clauses = _job_filters(
        skill=skill, experience=experience, city=city,
        fresh_days=fresh_days, require_logo=require_logo,
    )
    base = (
        select(JobMaster, Company)
        .join(Company, JobMaster.company_id == Company.id, isouter=True)
        .where(*clauses)
    )
    total = db.execute(
        select(func.count())
        .select_from(JobMaster)
        .join(Company, JobMaster.company_id == Company.id, isouter=True)
        .where(*clauses)
    ).scalar_one()

    rows = db.execute(
        base.order_by(
            JobMaster.posted_date.desc().nullslast(),
            JobMaster.scraped_at.desc(),
        ).limit(MAX_SCAN_ROWS)
    ).all()

    out: list[PartnerJob] = []
    seen_companies: set[str] = set()
    for job, company in rows:
        if one_per_company and company is not None:
            key = company.name.strip().lower()
            if key in seen_companies:
                continue
            seen_companies.add(key)
        out.append(_serialize(job, company))
        if len(out) >= limit:
            break
    return out, int(total)


def query_reel_suggestions(
    db: Session,
    *,
    fresh_days: int = 7,
    min_jobs: int = 4,
    limit: int = 10,
) -> list[ReelSuggestion]:
    """Ranked skill themes worth a reel this week — one scan of the fresh
    window, counted per curated skill, tower-side."""
    rows = db.execute(
        select(
            JobMaster.title,
            JobMaster.description_text,
            Company.name,
            Company.logo_url,
        )
        .join(Company, JobMaster.company_id == Company.id, isouter=True)
        .where(_freshness_clause(fresh_days))
        .limit(MAX_SUGGESTION_ROWS)
    ).all()

    counts: dict[str, int] = {}
    logo_companies: dict[str, set[str]] = {}
    for title, description, company_name, logo_url in rows:
        haystack = f'{title or ""}\n{description or ""}'.lower()
        for skill in SUGGESTION_SKILLS:
            if skill in haystack:
                counts[skill] = counts.get(skill, 0) + 1
                if logo_url and company_name:
                    logo_companies.setdefault(skill, set()).add(company_name)

    ranked = sorted(
        (
            ReelSuggestion(
                skill=skill,
                active_jobs=count,
                companies_with_logo=len(logo_companies.get(skill, ())),
            )
            for skill, count in counts.items()
            if count >= min_jobs
        ),
        key=lambda s: (-s.active_jobs, s.skill),
    )
    return ranked[:limit]


# ---------- routes ----------

@router.get('/jobs', response_model=JobsResponse, dependencies=[Depends(require_partner_token)])
def partner_jobs(
    skill: str | None = Query(default=None, min_length=2, max_length=60),
    experience: str | None = Query(default=None),
    city: str | None = Query(default=None, max_length=40),
    fresh_days: int = Query(default=7, ge=1, le=30),
    require_logo: bool = Query(default=True),
    one_per_company: bool = Query(default=True),
    limit: int = Query(default=6, ge=1, le=50),
    db: Session = Depends(get_db),
):
    if experience and normalize_experience(experience) is None:
        raise HTTPException(
            422,
            f'unknown experience band — use one of: {", ".join(sorted(VALID_EXPERIENCE_IDS))}',
        )
    jobs, total = query_partner_jobs(
        db, skill=skill, experience=experience, city=city,
        fresh_days=fresh_days, require_logo=require_logo,
        one_per_company=one_per_company, limit=limit,
    )
    return JobsResponse(jobs=jobs, total_matched=total, generated_at=datetime.now(timezone.utc))


@router.get(
    '/reel-suggestions',
    response_model=SuggestionsResponse,
    dependencies=[Depends(require_partner_token)],
)
def partner_reel_suggestions(
    fresh_days: int = Query(default=7, ge=1, le=30),
    min_jobs: int = Query(default=4, ge=1, le=100),
    limit: int = Query(default=10, ge=1, le=40),
    db: Session = Depends(get_db),
):
    suggestions = query_reel_suggestions(
        db, fresh_days=fresh_days, min_jobs=min_jobs, limit=limit,
    )
    return SuggestionsResponse(
        suggestions=suggestions, generated_at=datetime.now(timezone.utc),
    )


@router.get(
    '/health',
    response_model=PartnerHealth,
    dependencies=[Depends(require_partner_token)],
)
def partner_health(db: Session = Depends(get_db)):
    jobs_total = db.execute(select(func.count()).select_from(JobMaster)).scalar_one()
    freshest = db.execute(select(func.max(JobMaster.scraped_at))).scalar_one()
    return PartnerHealth(ok=True, jobs_total=int(jobs_total), freshest_scrape_at=freshest)
