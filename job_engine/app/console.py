"""Write human-readable activity entries for the live Console page.

Never raises: console logging must not break scraping or tasks.
"""

import logging

from app.db import SessionLocal
from app.models import ConsoleLog

logger = logging.getLogger(__name__)


def console_log(source: str, message: str, run_id: int | None = None, level: str = 'info'):
    if not message:
        return
    try:
        with SessionLocal() as db:
            db.add(ConsoleLog(source=source, level=level, run_id=run_id, message=message[:4000]))
            db.commit()
    except Exception:
        logger.warning('console_log failed', exc_info=True)
