"""Plan B — discovery-first detail enrich (2026-08-08).

Covers: card-first requirements extraction + honest fresher-track stamping,
the daily detail-page budget ledger, the idle/heat/budget trickle gate,
guest-seen-first priority ordering of pending enrich work, the off/light
mode guards on the Celery tasks, and the runtime mode toggle.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import detail_budget, runtime_settings
from app.db import Base
from app.models import JobMaster, ScrapeRun, SearchConfig
from app.tasks import card_requirements


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Card-first requirements (free, browser-less extraction at insert time)
# ---------------------------------------------------------------------------

class CardRequirementsTests(unittest.TestCase):
    def test_years_range_from_card_text(self):
        req, band, label = card_requirements(
            'Data Analyst · Acme Corp · Bengaluru · 3-5 years experience',
            'signal',
        )
        self.assertEqual(band, '3-5 years')
        self.assertEqual(req.experience_min_years, 3)
        self.assertEqual(req.experience_max_years, 5)
        self.assertEqual(label, '3-5 years')

    def test_fresher_wording_in_card(self):
        _req, band, _label = card_requirements(
            'Graduate Trainee — freshers welcome — Chennai', 'signal',
        )
        self.assertEqual(band, 'Fresher')

    def test_fresher_track_stamp_when_card_silent(self):
        """LinkedIn's own f_E=1,2 search filter is ground truth for the
        fresher track — a silent card still gets an honest band."""
        _req, band, label = card_requirements(
            'Software Engineer · Foo Ltd · Hyderabad', 'fresher',
        )
        self.assertEqual(band, 'Fresher')
        self.assertEqual(label, 'Fresher track (LinkedIn Internship/Entry)')

    def test_non_fresher_track_never_stamped(self):
        _req, band, label = card_requirements(
            'Software Engineer · Foo Ltd · Hyderabad', 'signal',
        )
        self.assertIsNone(band)
        self.assertIsNone(label)

    def test_card_years_beat_track_stamp(self):
        """A fresher-track card that STATES senior years keeps the stated
        truth — the stamp only fills silence, never overwrites."""
        _req, band, _label = card_requirements(
            'Engineering Manager · 9-12 years · Pune', 'fresher',
        )
        self.assertEqual(band, '9-12 years')


# ---------------------------------------------------------------------------
# Daily budget ledger
# ---------------------------------------------------------------------------

class FakeRedis:
    def __init__(self):
        self.store: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key):
        val = self.store.get(key)
        return None if val is None else str(val).encode()

    def incr(self, key):
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    def expire(self, key, ttl):
        self.ttls[key] = ttl


class DetailBudgetTests(unittest.TestCase):
    def test_consume_and_remaining(self):
        client = FakeRedis()
        self.assertEqual(detail_budget.used_today(client), 0)
        with mock.patch.object(detail_budget.config, 'DETAIL_BUDGET_PER_DAY', 3):
            self.assertEqual(detail_budget.remaining_today(client), 3)
            detail_budget.consume_page(client)
            detail_budget.consume_page(client)
            self.assertEqual(detail_budget.used_today(client), 2)
            self.assertEqual(detail_budget.remaining_today(client), 1)
            detail_budget.consume_page(client)
            detail_budget.consume_page(client)  # over-run never goes negative
            self.assertEqual(detail_budget.remaining_today(client), 0)

    def test_key_is_per_utc_day(self):
        from datetime import date

        self.assertNotEqual(
            detail_budget.budget_key(date(2026, 8, 8)),
            detail_budget.budget_key(date(2026, 8, 9)),
        )

    def test_ttl_set_so_old_days_expire(self):
        client = FakeRedis()
        detail_budget.consume_page(client)
        self.assertEqual(list(client.ttls.values()), [48 * 3600])

    def test_redis_failure_is_safe(self):
        class Broken:
            def get(self, key):
                raise ConnectionError('redis down')

            def incr(self, key):
                raise ConnectionError('redis down')

        self.assertEqual(detail_budget.used_today(Broken()), 0)
        self.assertEqual(detail_budget.consume_page(Broken()), 0)


# ---------------------------------------------------------------------------
# Trickle gate + priority ordering (in-memory SQLite)
# ---------------------------------------------------------------------------

def make_session():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def add_config(db, *, enabled=True, cron='0 5 * * *', last_run_at=None) -> SearchConfig:
    cfg = SearchConfig(
        name='AI Engineer', keywords='AI Engineer', enabled=enabled,
        schedule_cron=cron, last_run_at=last_run_at,
    )
    db.add(cfg)
    db.commit()
    return cfg


def add_job(db, cfg, *, linkedin_job_id: str, track: str = 'fresher',
            enriched_at=None, experience_label=None) -> JobMaster:
    job = JobMaster(
        linkedin_job_id=linkedin_job_id,
        title='Software Engineer',
        job_url=f'https://www.linkedin.com/jobs/view/{linkedin_job_id}/',
        source_track=track,
        search_config_id=cfg.id,
        requirements_enriched_at=enriched_at,
        experience_label=experience_label,
    )
    db.add(job)
    db.commit()
    return job


class CoolSnap:
    level = 'cool'
    detail = 'cpu=50C gpu=45C load=1.0'


class WarmSnap:
    level = 'warm'
    detail = 'cpu=70C gpu=65C load=3.0'


# Fixed clock so cron math never depends on when the suite runs:
# daily 05:00 UTC cron, last run 05:30 → next due tomorrow 05:00.
FIXED_NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
FIXED_LAST_RUN = datetime(2026, 8, 8, 5, 30, tzinfo=timezone.utc)


class TrickleGateTests(unittest.TestCase):
    def setUp(self):
        self.db = make_session()
        # Idle catalogue: one config whose next cron slot is far away
        add_config(self.db, last_run_at=FIXED_LAST_RUN)

        patches = [
            mock.patch('app.runtime_settings.get_detail_enrich_mode', return_value='light'),
            mock.patch.object(detail_budget, 'remaining_today', return_value=10),
            mock.patch('app.thermal.snapshot', return_value=CoolSnap()),
        ]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.mode_mock, self.budget_mock, self.heat_mock = self.mocks

    def _now_far_from_cron(self) -> datetime:
        """A moment >lookahead away from the daily 05:00 UTC cron slot."""
        return FIXED_NOW

    def test_open_when_idle_cool_and_budgeted(self):
        ok, reason = detail_budget.trickle_gate(self.db, now=self._now_far_from_cron())
        self.assertTrue(ok, reason)
        self.assertIn('idle + cool', reason)

    def test_blocked_when_mode_not_light(self):
        self.mode_mock.return_value = 'off'
        ok, reason = detail_budget.trickle_gate(self.db, now=self._now_far_from_cron())
        self.assertFalse(ok)
        self.assertIn('off', reason)

    def test_blocked_when_budget_spent(self):
        self.budget_mock.return_value = 0
        ok, reason = detail_budget.trickle_gate(self.db, now=self._now_far_from_cron())
        self.assertFalse(ok)
        self.assertIn('budget', reason)

    def test_blocked_while_a_search_runs(self):
        cfg = self.db.query(SearchConfig).first()
        self.db.add(ScrapeRun(search_config_id=cfg.id, status='running'))
        self.db.commit()
        ok, reason = detail_budget.trickle_gate(self.db, now=self._now_far_from_cron())
        self.assertFalse(ok)
        self.assertIn('search is running', reason)

    def test_blocked_when_search_due_within_lookahead(self):
        # 05:00 UTC daily cron; 04:50 is inside the 15-minute look-ahead
        now = datetime(2026, 8, 8, 4, 50, tzinfo=timezone.utc)
        cfg = self.db.query(SearchConfig).first()
        cfg.last_run_at = datetime(2026, 8, 7, 5, 30, tzinfo=timezone.utc)
        self.db.commit()
        ok, reason = detail_budget.trickle_gate(self.db, now=now)
        self.assertFalse(ok)
        self.assertIn('due within', reason)

    def test_blocked_by_queued_one_off_due_now(self):
        cfg = self.db.query(SearchConfig).first()
        self.db.add(ScrapeRun(
            search_config_id=cfg.id, status='queued', run_type='one_off',
            scheduled_for=None,  # NULL = due immediately
        ))
        self.db.commit()
        ok, reason = detail_budget.trickle_gate(self.db, now=self._now_far_from_cron())
        self.assertFalse(ok)
        self.assertIn('due within', reason)

    def test_blocked_when_warm(self):
        """Details never take the lane unless the host is fully Cool."""
        self.heat_mock.return_value = WarmSnap()
        ok, reason = detail_budget.trickle_gate(self.db, now=self._now_far_from_cron())
        self.assertFalse(ok)
        self.assertIn('warm', reason)


class PendingPriorityTests(unittest.TestCase):
    def test_guest_seen_then_fresher_then_rest(self):
        from app.enrichment import pending_requirement_ids

        db = make_session()
        cfg = add_config(db)
        oldest_signal = add_job(db, cfg, linkedin_job_id='100', track='signal')
        fresher = add_job(db, cfg, linkedin_job_id='200', track='fresher')
        newest_signal = add_job(db, cfg, linkedin_job_id='300', track='signal')
        delivered_signal = add_job(db, cfg, linkedin_job_id='400', track='signal')
        already_done = add_job(
            db, cfg, linkedin_job_id='500', track='fresher', enriched_at=utcnow(),
        )

        ids = pending_requirement_ids(db, limit=10, delivered_ids={'400'})
        self.assertEqual(
            ids,
            [delivered_signal.id, fresher.id, newest_signal.id, oldest_signal.id],
        )
        self.assertNotIn(already_done.id, ids)

    def test_enrich_failed_retries_after_cooldown(self):
        from app.enrichment import ENRICH_FAILED_RETRY_AFTER, pending_requirement_ids

        db = make_session()
        cfg = add_config(db)
        fresh_failure = add_job(
            db, cfg, linkedin_job_id='600', enriched_at=utcnow(),
            experience_label='enrich_failed',
        )
        old_failure = add_job(
            db, cfg, linkedin_job_id='700',
            enriched_at=utcnow() - ENRICH_FAILED_RETRY_AFTER - timedelta(minutes=5),
            experience_label='enrich_failed',
        )
        ids = pending_requirement_ids(db, limit=10, delivered_ids=set())
        self.assertIn(old_failure.id, ids)
        self.assertNotIn(fresh_failure.id, ids)


# ---------------------------------------------------------------------------
# Celery task guards (no browser, no Postgres touched)
# ---------------------------------------------------------------------------

class TaskGuardTests(unittest.TestCase):
    def test_enrich_task_paused_when_off(self):
        from app import tasks

        with mock.patch.object(tasks, 'get_detail_enrich_mode', return_value='off'):
            result = tasks.enrich_job_requirements(job_ids=[1, 2, 3])
        self.assertEqual(result, {'enriched': 0, 'paused': True, 'mode': 'off'})

    def test_enrich_task_skips_when_budget_spent(self):
        from app import tasks

        with mock.patch.object(tasks, 'get_detail_enrich_mode', return_value='light'), \
                mock.patch.object(detail_budget, 'remaining_today', return_value=0):
            result = tasks.enrich_job_requirements(job_ids=[1, 2, 3])
        self.assertEqual(result['skipped'], 'daily detail budget exhausted')

    def test_beat_paused_when_off(self):
        from app import tasks

        with mock.patch.object(tasks, 'get_detail_enrich_mode', return_value='off'):
            result = tasks.enrich_pending_requirements()
        self.assertEqual(result, {'paused': True, 'mode': 'off'})

    def test_beat_respects_closed_gate(self):
        from app import tasks

        with mock.patch.object(tasks, 'get_detail_enrich_mode', return_value='light'), \
                mock.patch.object(tasks, 'SessionLocal') as session_cls, \
                mock.patch.object(
                    detail_budget, 'trickle_gate',
                    return_value=(False, 'a search is running'),
                ):
            session_cls.return_value.__enter__.return_value = mock.MagicMock()
            result = tasks.enrich_pending_requirements()
        self.assertEqual(result, {'skipped': 'a search is running', 'mode': 'light'})

    def test_beat_runs_batch_when_gate_open(self):
        from app import tasks

        with mock.patch.object(tasks, 'get_detail_enrich_mode', return_value='light'), \
                mock.patch.object(tasks, 'SessionLocal') as session_cls, \
                mock.patch.object(
                    detail_budget, 'trickle_gate', return_value=(True, 'idle + cool'),
                ), \
                mock.patch.object(detail_budget, 'remaining_today', return_value=2), \
                mock.patch('app.enrichment.pending_requirement_ids', return_value=[]) as pending, \
                mock.patch('app.tasks.console_log'):
            session_cls.return_value.__enter__.return_value = mock.MagicMock()
            result = tasks.enrich_pending_requirements()
        # Batch capped by remaining budget (2), not DETAIL_BATCH_SIZE (6)
        pending.assert_called_once_with(mock.ANY, limit=2)
        self.assertEqual(result['note'], 'nothing pending')


# ---------------------------------------------------------------------------
# Runtime mode toggle (VIGIL-controlled, survives restarts)
# ---------------------------------------------------------------------------

class DetailEnrichModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(
            runtime_settings, '_PATH', Path(self.tmp.name) / 'runtime_settings.json',
        )
        patch.start()
        self.addCleanup(patch.stop)

    def test_default_falls_back_to_env_config(self):
        with mock.patch.object(
            runtime_settings.app_config, 'DETAIL_ENRICH_MODE', 'light',
        ):
            self.assertEqual(runtime_settings.get_detail_enrich_mode(), 'light')

    def test_bad_env_value_defaults_light(self):
        with mock.patch.object(
            runtime_settings.app_config, 'DETAIL_ENRICH_MODE', 'banana',
        ):
            self.assertEqual(runtime_settings.get_detail_enrich_mode(), 'light')

    def test_set_and_get_roundtrip(self):
        for mode in ('off', 'full', 'light'):
            runtime_settings.set_detail_enrich_mode(mode)
            self.assertEqual(runtime_settings.get_detail_enrich_mode(), mode)

    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError):
            runtime_settings.set_detail_enrich_mode('sometimes')


if __name__ == '__main__':
    unittest.main()
