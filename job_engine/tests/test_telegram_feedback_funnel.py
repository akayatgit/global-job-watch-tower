"""Result-feedback capture and daily guest-funnel analytics (kanban 2026-08-07).

Feedback: 👍/👎 a guest leaves on a results screen, readable back by Ashok.
Funnel: how many distinct guests, per UTC day, said hi -> finished the
button flow -> got real jobs -> came back on a later day.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from app.telegram_sessions import TelegramSessionStore


class FeedbackStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = TelegramSessionStore(Path(self.tmp.name) / 'bot.db')

    def tearDown(self):
        self.tmp.cleanup()

    def test_record_feedback_is_readable_back(self):
        self.sessions.record_feedback(
            'chat-1', rating=1, role_label='AI/ML', role_family='ai_ml',
            city='bengaluru', experience='fresher', had_results=True,
        )
        entries = self.sessions.list_feedback(limit=10)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['rating'], 1)
        self.assertEqual(entries[0]['role_label'], 'AI/ML')
        self.assertEqual(entries[0]['city'], 'bengaluru')
        self.assertTrue(entries[0]['had_results'])

    def test_feedback_summary_counts_up_and_down_separately(self):
        self.sessions.record_feedback('chat-1', rating=1)
        self.sessions.record_feedback('chat-2', rating=1)
        self.sessions.record_feedback('chat-3', rating=-1)
        summary = self.sessions.feedback_summary(days=7)
        self.assertEqual(summary['total'], 3)
        self.assertEqual(summary['up'], 2)
        self.assertEqual(summary['down'], 1)

    def test_feedback_outside_the_window_is_excluded_from_summary(self):
        old_ts = time.time() - 30 * 86400
        self.sessions.record_feedback('chat-old', rating=1)
        with self.sessions._lock, self.sessions._connect() as conn:
            conn.execute('UPDATE result_feedback SET created_at=?', (old_ts,))
        summary = self.sessions.feedback_summary(days=7)
        self.assertEqual(summary['total'], 0)

    def test_list_feedback_orders_latest_first_and_respects_limit(self):
        for i in range(5):
            self.sessions.record_feedback(f'chat-{i}', rating=1, role_label=f'role-{i}')
        entries = self.sessions.list_feedback(limit=3)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]['role_label'], 'role-4')

    def test_no_feedback_yields_empty_summary_not_a_crash(self):
        summary = self.sessions.feedback_summary()
        self.assertEqual(summary['total'], 0)
        self.assertEqual(summary['up'], 0)
        self.assertEqual(summary['down'], 0)
        self.assertEqual(self.sessions.list_feedback(), [])


class FunnelEventTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = TelegramSessionStore(Path(self.tmp.name) / 'bot.db')

    def tearDown(self):
        self.tmp.cleanup()

    def test_greeted_event_counts_a_distinct_chat_once_per_day(self):
        self.sessions.record_funnel_event('chat-1', 'greeted')
        self.sessions.record_funnel_event('chat-1', 'greeted')  # repeat same day
        self.sessions.record_funnel_event('chat-2', 'greeted')
        today = self.sessions.funnel_daily(days=1)[0]
        self.assertEqual(today['greeted'], 2)

    def test_full_funnel_progression_counts_every_stage(self):
        self.sessions.record_funnel_event('chat-1', 'greeted')
        self.sessions.record_funnel_event('chat-1', 'finished_flow')
        self.sessions.record_funnel_event('chat-1', 'got_jobs')
        today = self.sessions.funnel_daily(days=1)[0]
        self.assertEqual(today['greeted'], 1)
        self.assertEqual(today['finished_flow'], 1)
        self.assertEqual(today['got_jobs'], 1)
        self.assertEqual(today['returned'], 0)

    def test_a_second_greeting_on_a_later_day_is_recorded_as_returned(self):
        yesterday = time.time() - 86400
        self.sessions.record_funnel_event('chat-1', 'greeted', when=yesterday)
        self.sessions.record_funnel_event('chat-1', 'greeted')  # today
        rows = self.sessions.funnel_daily(days=2)
        today = rows[-1]
        self.assertEqual(today['greeted'], 1)
        self.assertEqual(today['returned'], 1)

    def test_a_brand_new_guest_never_counts_as_returned(self):
        self.sessions.record_funnel_event('chat-new', 'greeted')
        today = self.sessions.funnel_daily(days=1)[0]
        self.assertEqual(today['returned'], 0)

    def test_finished_flow_without_a_prior_greeting_never_counts_as_returned(self):
        """A same-day 'finished_flow' with no earlier day's activity must not
        be mistaken for a returning guest — only a later 'greeted' does."""
        self.sessions.record_funnel_event('chat-1', 'finished_flow')
        self.sessions.record_funnel_event('chat-1', 'greeted')
        today = self.sessions.funnel_daily(days=1)[0]
        self.assertEqual(today['returned'], 0)

    def test_funnel_daily_fills_in_zero_for_days_with_no_activity(self):
        rows = self.sessions.funnel_daily(days=5)
        self.assertEqual(len(rows), 5)
        for row in rows:
            self.assertEqual(row['greeted'], 0)
            self.assertEqual(row['finished_flow'], 0)
            self.assertEqual(row['got_jobs'], 0)
            self.assertEqual(row['returned'], 0)

    def test_funnel_daily_is_sorted_oldest_to_newest(self):
        rows = self.sessions.funnel_daily(days=3)
        days = [row['day'] for row in rows]
        self.assertEqual(days, sorted(days))


if __name__ == '__main__':
    unittest.main()
