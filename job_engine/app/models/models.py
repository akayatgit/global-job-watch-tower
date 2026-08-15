from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# SQLite only autoincrements plain INTEGER primary keys; Postgres is unaffected
BigIntPK = BigInteger().with_variant(Integer, 'sqlite')


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Company(Base):
    __tablename__ = 'companies'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    # Profile enrich (logo + size + followers + casual punchline)
    logo_url: Mapped[str | None] = mapped_column(String(800), nullable=True)
    tagline: Mapped[str | None] = mapped_column(String(400), nullable=True)
    punchline: Mapped[str | None] = mapped_column(String(400), nullable=True)
    about_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    follower_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    employee_count_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    employee_count_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    employee_count_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    profile_enriched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )
    watched: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    watched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    jobs: Mapped[list['JobMaster']] = relationship(back_populates='company')


class SearchConfig(Base):
    __tablename__ = 'search_configs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    keywords: Mapped[str] = mapped_column(String(300))
    geo_id: Mapped[str] = mapped_column(String(50), default='102713980')
    location_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sector: Mapped[str] = mapped_column(String(100), default='software')
    # LinkedIn experience filter f_E values, comma-joined (e.g. "1,2" = Intern+Entry).
    # Empty/null = no f_E (all seniorities) — used by Market Signal track.
    experience_filter: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # fresher = graduate flywheel; signal = experienced / economy hiring signals
    track: Mapped[str] = mapped_column(String(20), default='fresher', index=True)
    # MNC-first collection (2026-08-14): when set, this search is scoped to
    # ONE watched company — pipe-separated match needles, first = display
    # name. Insert keeps only jobs whose card company matches; the AI
    # relevance filter is skipped (see app/mnc_watchlist.py).
    target_company: Mapped[str | None] = mapped_column(String(300), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    schedule_cron: Mapped[str] = mapped_column(String(100), default='0 * * * *')  # hourly
    priority: Mapped[int] = mapped_column(Integer, default=5)
    max_pages: Mapped[int] = mapped_column(Integer, default=10)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    runs: Mapped[list['ScrapeRun']] = relationship(back_populates='search_config')


class ScrapeRun(Base):
    __tablename__ = 'scrape_runs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_config_id: Mapped[int] = mapped_column(ForeignKey('search_configs.id'), index=True)
    run_type: Mapped[str] = mapped_column(String(20), default='scheduled')  # scheduled | one_off
    target_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    # queued | dispatched | running | cancel_requested | success | failed | cancelled
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pages_scraped: Mapped[int] = mapped_column(Integer, default=0)
    jobs_found: Mapped[int] = mapped_column(Integer, default=0)
    jobs_inserted: Mapped[int] = mapped_column(Integer, default=0)
    last_request_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    search_config: Mapped['SearchConfig'] = relationship(back_populates='runs')
    requests: Mapped[list['RequestLog']] = relationship(back_populates='scrape_run')


class JobMaster(Base):
    __tablename__ = 'jobs_master'

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    linkedin_job_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    company_id: Mapped[int | None] = mapped_column(ForeignKey('companies.id'), nullable=True, index=True)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    city_key: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    sector: Mapped[str] = mapped_column(String(100), default='software')
    job_url: Mapped[str] = mapped_column(String(800))
    posted_date: Mapped[datetime | None] = mapped_column(Date, nullable=True, index=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Detail-page requirements (employability graph clusters)
    experience_min_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    experience_max_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    experience_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    experience_band: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    seniority_level: Mapped[str | None] = mapped_column(String(80), nullable=True)
    degrees: Mapped[list | None] = mapped_column(JSON, nullable=True)
    certifications: Mapped[list | None] = mapped_column(JSON, nullable=True)
    domains: Mapped[list | None] = mapped_column(JSON, nullable=True)
    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements_enriched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )
    # AI reading of description_text (quote-grounded, app/ai_requirements.py):
    # verdict TRUE = employer explicitly welcomes freshers, evidence = the
    # verbatim sentence, ai_read_at NULL = not read yet (beat backfills).
    ai_fresher_verdict: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ai_fresher_evidence: Mapped[str | None] = mapped_column(String(400), nullable=True)
    ai_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # Immutable provenance captured when this job was first stored. Search
    # definitions may change track later; historical fresher scope must not.
    source_track: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    search_config_id: Mapped[int | None] = mapped_column(ForeignKey('search_configs.id'), nullable=True)
    scrape_run_id: Mapped[int | None] = mapped_column(ForeignKey('scrape_runs.id'), nullable=True)

    company: Mapped['Company | None'] = relationship(back_populates='jobs')

    __table_args__ = (
        Index('ix_jobs_sector_scraped', 'sector', 'scraped_at'),
        Index('ix_jobs_city_scraped', 'city_key', 'scraped_at'),
    )


class RequestLog(Base):
    __tablename__ = 'request_log'

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    scrape_run_id: Mapped[int] = mapped_column(ForeignKey('scrape_runs.id'), index=True)
    page_num: Mapped[int] = mapped_column(Integer, default=0)
    url: Mapped[str] = mapped_column(String(1000))
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scrape_run: Mapped['ScrapeRun'] = relationship(back_populates='requests')


class ConsoleLog(Base):
    """Human-readable live activity feed shown on the Console page."""

    __tablename__ = 'console_log'

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    source: Mapped[str] = mapped_column(String(30), default='app')  # scraper | ai | worker | beat | app
    level: Mapped[str] = mapped_column(String(10), default='info')
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    message: Mapped[str] = mapped_column(Text)


class TowerEvent(Base):
    """Structured pulse events for Tower Health (filter mode, browser open)."""

    __tablename__ = 'tower_events'

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    # ollama_filter | keyword_filter | browser_open | scrape_done
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    detail: Mapped[str] = mapped_column(String(1000), default='')
