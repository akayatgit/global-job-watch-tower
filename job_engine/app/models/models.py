from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
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
    sector: Mapped[str] = mapped_column(String(100), default='software')
    job_url: Mapped[str] = mapped_column(String(800))
    posted_date: Mapped[datetime | None] = mapped_column(Date, nullable=True, index=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_config_id: Mapped[int | None] = mapped_column(ForeignKey('search_configs.id'), nullable=True)
    scrape_run_id: Mapped[int | None] = mapped_column(ForeignKey('scrape_runs.id'), nullable=True)

    company: Mapped['Company | None'] = relationship(back_populates='jobs')

    __table_args__ = (
        Index('ix_jobs_sector_scraped', 'sector', 'scraped_at'),
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
