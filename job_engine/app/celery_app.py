from celery import Celery

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
    },
)
