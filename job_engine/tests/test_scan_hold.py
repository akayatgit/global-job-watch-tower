"""Reverse prompt breaks /promptscan for 15 minutes."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.prompts import scan_hold


class _FakeRedis:
    def __init__(self):
        self.kv: dict[str, str] = {}

    def set(self, key, value, ex=None):
        self.kv[key] = value
        return True

    def get(self, key):
        return self.kv.get(key)


class _FakeControl:
    def __init__(self, active=None):
        self.revoked: list[tuple] = []
        self._active = active or {
            'worker@host': [
                {'id': 'scan-1', 'name': 'app.tasks.daily_prompt_pipeline'},
                {'id': 'rev-9', 'name': 'app.tasks.reverse_prompt_video'},
            ],
        }

    def inspect(self, timeout=2):
        return self

    def active(self):
        return self._active

    def reserved(self):
        return {}

    def scheduled(self):
        return {}

    def revoke(self, tid, terminate=False, signal=None):
        self.revoked.append((tid, terminate, signal))


class ScanHoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / 'scan_hold_until'
        self.redis = _FakeRedis()
        self.patches = [
            mock.patch.object(scan_hold, '_FILE', self.file),
            mock.patch.object(scan_hold, '_redis', lambda: self.redis),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def test_hold_and_expiry(self):
        left = scan_hold.hold_scan(seconds=900, now=1_000.0)
        self.assertEqual(left, 900)
        self.assertTrue(scan_hold.is_held(now=1_000.0))
        self.assertEqual(scan_hold.remaining_s(now=1_100.0), 800)
        self.assertFalse(scan_hold.is_held(now=2_000.0))

    def test_second_igtovid_extends_the_hold(self):
        scan_hold.hold_scan(seconds=100, now=1_000.0)
        scan_hold.hold_scan(seconds=900, now=1_050.0)
        self.assertGreaterEqual(scan_hold.remaining_s(now=1_050.0), 899)

    def test_break_revokes_scan_not_reverse(self):
        control = _FakeControl()
        result = scan_hold.break_prompt_scan(seconds=900, control=control)
        self.assertEqual(result['held_s'], 900)
        self.assertEqual(result['revoked'], 1)
        self.assertEqual(control.revoked, [('scan-1', True, 'SIGTERM')])
        self.assertTrue(scan_hold.is_held())

    def test_raise_if_held(self):
        scan_hold.hold_scan(seconds=60, now=10.0)
        with self.assertRaises(scan_hold.ReverseHold):
            scan_hold.raise_if_held(now=10.0)
        scan_hold.raise_if_held(now=80.0)


class ScanTaskHoldTests(unittest.TestCase):
    def test_pipeline_skips_when_held(self):
        from app import tasks

        with mock.patch.object(scan_hold, 'is_held', return_value=True), \
                mock.patch.object(scan_hold, 'remaining_s', return_value=400), \
                mock.patch.object(tasks, 'console_log'):
            out = tasks.daily_prompt_pipeline.run(force=False)
        self.assertEqual(out['skipped'], 'reverse-hold')
        self.assertEqual(out['resume_in_s'], 400)

    def test_idle_kick_does_not_start_during_hold(self):
        from app import tasks

        class _Db:
            def scalar(self, *_a, **_k):
                return 0

        class _Ctx:
            def __enter__(self):
                return _Db()

            def __exit__(self, *args):
                return False

        with mock.patch.object(tasks, 'SessionLocal', lambda: _Ctx()), \
                mock.patch.object(tasks, 'daily_prompt_pipeline') as pipe, \
                mock.patch.object(scan_hold, 'is_held', return_value=True), \
                mock.patch.object(scan_hold, 'remaining_s', return_value=77), \
                mock.patch('app.prompts.pipeline.idle_scan_reason', return_value='empty-catalogue'):
            result = tasks._maybe_dispatch_idle_prompt_scan()
        self.assertFalse(result['kicked'])
        self.assertEqual(result['reason'], 'reverse-hold')
        pipe.delay.assert_not_called()
