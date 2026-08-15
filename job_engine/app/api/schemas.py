from datetime import date, datetime

from pydantic import BaseModel, Field


class ConfigIn(BaseModel):
    name: str
    keywords: str
    geo_id: str = '102713980'
    location_label: str | None = None
    sector: str = 'software'
    experience_filter: str | None = '1,2'
    track: str = 'fresher'
    enabled: bool = True
    schedule_cron: str = '0 * * * *'
    priority: int = 5
    max_pages: int = Field(default=10, ge=1, le=40)


class ConfigOut(ConfigIn):
    id: int
    last_run_at: datetime | None
    created_at: datetime

    model_config = {'from_attributes': True}


class RunRequest(BaseModel):
    search_config_id: int
    scheduled_for: datetime | None = None  # None = run now


class RunOut(BaseModel):
    id: int
    search_config_id: int
    run_type: str
    status: str
    target_date: date | None
    scheduled_for: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    pages_scraped: int
    jobs_found: int
    jobs_inserted: int
    last_request_at: datetime | None
    error: str | None

    model_config = {'from_attributes': True}


class JobOut(BaseModel):
    id: int
    linkedin_job_id: str
    title: str
    company: str | None = None
    location: str | None
    city_key: str | None = None
    sector: str
    experience_band: str | None = None
    source_track: str | None = None
    job_url: str
    posted_date: date | None
    scraped_at: datetime
    # Employer-stated only (AI quote-grounded / LinkedIn criteria) — None
    # whenever the posting never mentioned them.
    salary_text: str | None = None
    industry: str | None = None

    model_config = {'from_attributes': True}
