from celery import Celery
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

