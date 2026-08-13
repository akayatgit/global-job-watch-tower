"""Engine-stall detection for Tower Health.

2026-08-13 incident: the Celery worker/beat died mid-run and the /health
board kept saying "Tower healthy" for 24h+ — a Junior Software Developer
run sat in status 'running', all today/24h counters were 0, and day-old
"Recent pulses" looked live because they carried no timestamps. These tests
lock the honest behaviour: a run alive far past the reaper window, or an
overdue backlog nobody dispatches, must flip the alert to 'stalled'.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app import config
from app.tower_health import _age_label, _detect_stall


NOW = datetime(2026, 8, 13, 15, 20, tzinfo=timezone.utc)


def detect(**kwargs):
    defaults = dict(
        running_started_at=None,
        running_name='—',
        newest_started_at=None,
        backlog=0,
        allow_new=True,
        now=NOW,
    )
    defaults.update(kwargs)
    return _detect_stall(**defaults)


class StuckRunTests(unittest.TestCase):
    def test_run_stuck_past_reaper_window_is_stalled(self):
        stalled, detail = detect(
            running_started_at=NOW - timedelta(hours=26),
            running_name='Junior Software Developer',
        )
        self.assertTrue(stalled)
        self.assertIn('Junior Software Developer', detail)
        self.assertIn('restart', detail.lower())

    def test_healthy_active_run_is_not_stalled(self):
        stalled, detail = detect(
            running_started_at=NOW - timedelta(minutes=10),
            running_name='Junior Software Developer',
        )
        self.assertFalse(stalled)
        self.assertEqual(detail, '')

    def test_run_inside_reaper_grace_is_not_stalled(self):
        # Reaper fails runs at STALE_RUN_MINUTES; we alarm only past +15 grace
        stalled, _ = detect(
            running_started_at=NOW - timedelta(minutes=config.STALE_RUN_MINUTES + 5),
            running_name='Data Analyst',
        )
        self.assertFalse(stalled)

    def test_naive_timestamp_is_treated_as_utc(self):
        stalled, _ = detect(
            running_started_at=(NOW - timedelta(hours=3)).replace(tzinfo=None),
            running_name='Data Analyst',
            now=NOW,
        )
        self.assertTrue(stalled)


class DeadBeatTests(unittest.TestCase):
    def test_overdue_backlog_with_long_idle_is_stalled(self):
        stalled, detail = detect(
            backlog=3,
            newest_started_at=NOW - timedelta(hours=5),
        )
        self.assertTrue(stalled)
        self.assertIn('3 search', detail)
        self.assertIn('beat', detail.lower())

    def test_backlog_with_recent_start_is_not_stalled(self):
        stalled, _ = detect(
            backlog=3,
            newest_started_at=NOW - timedelta(minutes=5),
        )
        self.assertFalse(stalled)

    def test_heat_pause_never_counts_as_stall(self):
        stalled, _ = detect(
            backlog=3,
            newest_started_at=NOW - timedelta(hours=5),
            allow_new=False,
        )
        self.assertFalse(stalled)

    def test_fresh_install_with_no_runs_ever_is_not_stalled(self):
        stalled, _ = detect(backlog=3, newest_started_at=None)
        self.assertFalse(stalled)

    def test_no_backlog_no_running_is_not_stalled(self):
        stalled, _ = detect(backlog=0, newest_started_at=NOW - timedelta(days=2))
        self.assertFalse(stalled)


class AgeLabelTests(unittest.TestCase):
    def test_minutes_hours_days(self):
        self.assertEqual(_age_label(timedelta(minutes=42)), '42m')
        self.assertEqual(_age_label(timedelta(hours=26)), '26h')
        self.assertEqual(_age_label(timedelta(days=2, hours=3)), '2d 3h')


if __name__ == '__main__':
    unittest.main()
