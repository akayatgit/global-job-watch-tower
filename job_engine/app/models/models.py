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
    # relevance filter is skipped (see app/mnc_watchlist.py). The sentinel
    # '*' (2026-08-19, app/gtm_role_searches.py) means "any watched company".
    target_company: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # LinkedIn f_WT workplace filter: 1=on-site, 2=remote, 3=hybrid.
    # Empty/null = no filter. GTM Remote hunting searches use '2'.
    work_type_filter: Mapped[str | None] = mapped_column(String(10), nullable=True)
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
    # Employer-stated facts (only when mentioned): skills from the AI read
    # (each grounded verbatim in the description), industry from LinkedIn's
    # own criteria block first / AI fallback, salary as the verbatim snippet.
    skills: Mapped[list | None] = mapped_column(JSON, nullable=True)
    industry: Mapped[str | None] = mapped_column(String(160), nullable=True)
    salary_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
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


class VideoPrompt(Base):
    """One collected AI video prompt (Prompt Tower, 2026-09-09 pivot).

    Prompts are the product now. Every row keeps its provenance (where it
    was found, who wrote it) so the Instagram post can credit the source
    and so the scorer can never be fed text nobody actually published.
    """

    __tablename__ = 'video_prompts'

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    # sha1 of the normalized text — exact-duplicate guard across sources
    fingerprint: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    text: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # reddit | instagram | web | promptbase | manual
    source: Mapped[str] = mapped_column(String(40), index=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    # Which video model the prompt targets when stated (veo | kling | sora | runway | …)
    model_hint: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Product category guess from the text (perfume, skincare, beverage, …)
    category: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    # Deterministic pre-score (0–100) from vocabulary/structure — never LLM-authored
    heuristic_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Hermes/Ollama rubric: detail + flow (0–100 each), overall, reasons
    ai_detail: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_flow: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Blend of heuristic + AI; the number the shortlist ranks on
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    # Baseline snapshot used when this row was scored (mean/std of proven
    # winners in the RAG) and whether it beat the baseline by > 1σ
    baseline_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_std: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_outlier: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # new | shortlisted | posted | rejected
    status: Mapped[str] = mapped_column(String(20), default='new', index=True)
    # Owner rating 1–5 (Telegram ⭐ buttons) + Instagram performance after posting
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    performance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    performance_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Proven winner — used as a few-shot exemplar + baseline for scoring
    exemplar: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    shortlists: Mapped[list['PromptShortlist']] = relationship(back_populates='prompt')
    renders: Mapped[list['PromptRender']] = relationship(back_populates='prompt')


class PromptShortlist(Base):
    """Top-10 of one UTC day — the list Ashok gets on Telegram."""

    __tablename__ = 'prompt_shortlists'

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    day: Mapped[datetime] = mapped_column(Date, index=True)
    rank: Mapped[int] = mapped_column(Integer)
    prompt_id: Mapped[int] = mapped_column(ForeignKey('video_prompts.id'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    prompt: Mapped['VideoPrompt'] = relationship(back_populates='shortlists')

    __table_args__ = (
        Index('ux_prompt_shortlists_day_rank', 'day', 'rank', unique=True),
    )


class PromptRender(Base):
    """One approved prompt + product image → AI video job."""

    __tablename__ = 'prompt_renders'

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey('video_prompts.id'), index=True)
    chat_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Partner asset keys (served by /api/partner/v1/assets/{key})
    product_image_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    card_image_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    video_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    video_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # The post asset: raw clip composited into the card template as a video
    # (title · clip · storyboard | scrolling prompt). Missing = reel failed;
    # reel_error says why (ffmpeg absent…) while the raw clip is still usable.
    reel_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    reel_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    reel_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # queued | running | done | failed
    status: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    prompt: Mapped['VideoPrompt'] = relationship(back_populates='renders')


class ReversePrompt(Base):
    """Reverse prompt (2026-09-10): a best-performing Instagram / Pinterest
    product video → download → Gemini writes the timestamped prompt that
    would recreate it → the same reel template (clip · storyboard ·
    scrolling prompt) → post-ready MP4. Owner /igtovid · /pintovid."""

    __tablename__ = 'reverse_prompts'

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    chat_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # instagram | pinterest | direct | upload (video file sent in Telegram)
    platform: Mapped[str] = mapped_column(String(20), default='upload')
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Where the media actually came from (the resolved mp4 / m3u8 URL)
    media_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    video_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    video_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Owner-typed header on the cinematic reel (asked after the URL)
    header_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Owner pick after the title: gemini | astra | fable
    vision_engine: Mapped[str] = mapped_column(String(20), default='gemini')
    # What the vision model wrote — stored verbatim, the reel shows it as-is
    keyword: Mapped[str | None] = mapped_column(String(60), nullable=True)
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Cut-based recreate frames (JSON [{t, key, filename}]) — not the reel storyboard
    ref_frames: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # The catalogue row this prompt also became (when the gate accepted it)
    prompt_id: Mapped[int | None] = mapped_column(ForeignKey('video_prompts.id'), nullable=True)
    reel_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    reel_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    reel_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # queued | downloading | describing | composing | done | failed
    status: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
