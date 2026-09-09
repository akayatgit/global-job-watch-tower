from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready

from app import config

celery = Celery(
    'job_engine',
    broker=config.REDIS_URL,
    backend=config.REDIS_URL,
    include=['app.tasks'],
)

celery.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,   # one browser job at a time
    task_track_started=True,
    timezone='UTC',
    enable_utc=True,
    beat_schedule={
        'enqueue-due-configs': {
            'task': 'app.tasks.enqueue_due_work',
            'schedule': float(config.BEAT_SCAN_INTERVAL_S),
        },
        # Backfill experience / degree / cert / domain from job detail pages
        'enrich-pending-requirements': {
            'task': 'app.tasks.enrich_pending_requirements',
            'schedule': 600.0,  # every 10 minutes
        },
        # Backfill company logo / followers / size / punchline
        'enrich-pending-companies': {
            'task': 'app.tasks.enrich_pending_companies',
            'schedule': 900.0,  # every 15 minutes
        },
        # AI-read stored descriptions skipped inline (heat/busy) — no browser
        'ai-read-pending-descriptions': {
            'task': 'app.tasks.ai_read_pending_descriptions',
            'schedule': 600.0,  # every 10 minutes
        },
        # Prompt Tower (2026-09-09): one daily collect → score → top-10 run
        # (03:30 UTC = 09:00 IST by default), plus a 10-min scoring sweep
        # for prompts that arrived unscored (manual adds, heat skips).
        'daily-prompt-pipeline': {
            'task': 'app.tasks.daily_prompt_pipeline',
            'schedule': crontab(
                hour=config.PROMPT_PIPELINE_UTC_HOUR,
                minute=config.PROMPT_PIPELINE_UTC_MINUTE,
            ),
        },
        'score-pending-prompts': {
            'task': 'app.tasks.score_pending_prompts',
            'schedule': 600.0,
        },
    },
)


@worker_ready.connect
def _clear_orphans_on_boot(**_kwargs):
    """Previous worker dies leave 'running' rows that block the whole queue."""
    from datetime import datetime, timezone
    from app.db import SessionLocal
    from app.tasks import _reap_stale_runs

    with SessionLocal() as db:
        n = _reap_stale_runs(
            db,
            datetime.now(timezone.utc),
            minutes=2,
            reason=(
                'Orphan cleared on worker start — previous browser session '
                'did not finish (restart/crash).'
            ),
        )
    if n:
        import logging
        logging.getLogger(__name__).warning('cleared %s orphan scrape(s) on boot', n)

