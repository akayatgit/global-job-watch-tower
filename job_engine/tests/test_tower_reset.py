"""Base-level tower data reset (Ashok, 2026-08-14).

Wipes caught data, keeps definitions + watchlist + guest assets, cancels
in-flight runs gracefully (rows kept — a running worker re-reads its row),
and reschedules every search by clearing last_run_at so the beat refills
the tower immediately.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    Company,
    JobMaster,
    RequestLog,
    ScrapeRun,
    SearchConfig,
    TowerEvent,
)
from app.tower_reset import reset_preview, reset_tower_data


def make_session():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


class TowerResetTests(unittest.TestCase):
    def setUp(self):
        self.db = make_session()
        self.cfg = SearchConfig(
            name='MNC · Deloitte — Fresher', keywords='"Deloitte"',
            enabled=True, schedule_cron='0 5 * * *',
            target_company='Deloitte',
            last_run_at=datetime(2026, 8, 14, 5, 0, tzinfo=timezone.utc),
        )
        self.db.add(self.cfg)
        self.db.commit()
        self.watched = Company(name='Deloitte', watched=True, logo_url='https://x/logo.png')
        self.unwatched = Company(name='Tiny Startup LLP', watched=False)
        self.db.add_all([self.watched, self.unwatched])
        self.db.commit()
        self.done_run = ScrapeRun(
            search_config_id=self.cfg.id, status='success',
        )
        self.active_run = ScrapeRun(
            search_config_id=self.cfg.id, status='running',
        )
        self.db.add_all([self.done_run, self.active_run])
        self.db.commit()
        self.db.add_all([
            JobMaster(
                linkedin_job_id='111', title='Analyst',
                job_url='https://www.linkedin.com/jobs/view/111/',
                company_id=self.watched.id, scrape_run_id=self.done_run.id,
            ),
            JobMaster(
                linkedin_job_id='222', title='Consultant',
                job_url='https://www.linkedin.com/jobs/view/222/',
                company_id=self.unwatched.id,
            ),
            RequestLog(scrape_run_id=self.done_run.id, url='https://x/1'),
        ])
        self.db.commit()

    def test_preview_counts_and_active_names(self):
        preview = reset_preview(self.db)
        self.assertEqual(preview['jobs'], 2)
        self.assertEqual(preview['runs'], 2)
        self.assertEqual(preview['request_logs'], 1)
        self.assertEqual(preview['companies'], 2)
        self.assertEqual(preview['companies_watched_kept'], 1)
        self.assertEqual(preview['companies_unwatched_wiped'], 1)
        self.assertEqual(preview['active_searches'], ['MNC · Deloitte — Fresher'])

    def test_reset_wipes_data_keeps_definitions_and_watchlist(self):
        result = reset_tower_data(self.db, purge_queue=False)
        self.assertTrue(result['done'])
        self.assertEqual(self.db.query(JobMaster).count(), 0)
        self.assertEqual(self.db.query(RequestLog).count(), 0)
        companies = self.db.execute(select(Company)).scalars().all()
        self.assertEqual([c.name for c in companies], ['Deloitte'])
        self.assertEqual(companies[0].logo_url, 'https://x/logo.png')
        self.assertEqual(self.db.query(SearchConfig).count(), 1)

    def test_active_run_is_cancelled_gracefully_and_its_row_kept(self):
        """A running worker re-reads its run row before every page
        (scalar_one) — deleting it would crash the worker mid-scrape."""
        reset_tower_data(self.db, purge_queue=False)
        runs = self.db.execute(select(ScrapeRun)).scalars().all()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].id, self.active_run.id)
        self.assertEqual(runs[0].status, 'cancel_requested')
        self.assertEqual(runs[0].error, 'cancelled for tower data reset')

    def test_queued_runs_cancel_immediately(self):
        self.active_run.status = 'queued'
        self.db.commit()
        result = reset_tower_data(self.db, purge_queue=False)
        self.db.refresh(self.active_run)
        self.assertEqual(self.active_run.status, 'cancelled')
        self.assertEqual(result['cancelled_active'], ['MNC · Deloitte — Fresher'])

    def test_every_search_becomes_immediately_due_again(self):
        """Clearing last_run_at is the refill trigger: the beat computes
        due-ness from last_run_at or created_at, so a wiped tower starts
        re-scraping on the next tick instead of waiting for tomorrow."""
        reset_tower_data(self.db, purge_queue=False)
        self.db.refresh(self.cfg)
        self.assertIsNone(self.cfg.last_run_at)
        self.assertTrue(self.cfg.enabled)

    def test_reset_leaves_an_audit_event(self):
        reset_tower_data(self.db, purge_queue=False)
        event = self.db.execute(
            select(TowerEvent).where(TowerEvent.kind == 'tower_reset')
        ).scalar_one()
        self.assertIn('wiped 2 jobs', event.detail)

    def test_idle_tower_reset_reports_no_disturbance(self):
        self.active_run.status = 'success'
        self.db.commit()
        result = reset_tower_data(self.db, purge_queue=False)
        self.assertEqual(result['cancelled_active'], [])
        self.assertEqual(self.db.query(ScrapeRun).count(), 0)


if __name__ == '__main__':
    unittest.main()
