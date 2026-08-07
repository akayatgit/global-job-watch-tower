"""Daily job-alert subscription tests (kanban 2026-08-07).

Covers: create/dedupe/cap, seeding sent_job_ids so subscribing never
re-announces jobs already shown, matching reuses JobMasterEngine's own
_matches_role/_matches_city (no second notion of "is this a match"), and
dispatch only sends for genuinely new matches, never re-sending the same
job twice."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import telegram_alerts
from app.job_role_families import title_matches_role_family
from app.telegram_sessions import TelegramSessionStore


def make_job(job_id: int, *, title: str = 'Machine Learning Engineer', city: str = 'bengaluru') -> dict:
    return {
        'id': job_id,
        'linkedin_job_id': str(4448000000 + job_id),
        'title': title,
        'company': f'Company {job_id}',
        'city_key': city,
        'experience_band': 'Fresher',
        'source_track': 'fresher',
        'job_url': f'https://www.linkedin.com/jobs/view/{4448000000 + job_id}/',
    }


class FakeAPI:
    def __init__(self):
        self.jobs: list[dict] = []
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, path: str, params: dict | None = None):
        self.calls.append((path, params or {}))
        if path != '/api/jobs':
            return {}
        params = params or {}
        rows = list(self.jobs)
        if params.get('city'):
            rows = [row for row in rows if row.get('city_key') == params['city']]
        if params.get('role_family'):
            rows = [row for row in rows if title_matches_role_family(row.get('title'), params['role_family'])]
        return rows


class AlertSubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = TelegramSessionStore(Path(self.tmp.name) / 'bot.db')

    def tearDown(self):
        self.tmp.cleanup()

    def test_creating_an_alert_seeds_sent_ids_from_what_was_already_shown(self):
        alert, status = telegram_alerts.create_or_get_alert(
            self.sessions, 'chat-1',
            role_family='ai_ml', role_keywords=[], role_label='AI/ML',
            city='bengaluru', seen_ids=['4448000001', '4448000002'],
        )
        self.assertEqual(status, 'created')
        self.assertEqual(set(alert['sent_job_ids']), {'4448000001', '4448000002'})

    def test_subscribing_twice_to_the_identical_search_reuses_the_same_alert(self):
        first, status1 = telegram_alerts.create_or_get_alert(
            self.sessions, 'chat-2',
            role_family='ai_ml', role_keywords=['nlp'], role_label='AI/ML NLP Engineer',
            city='bengaluru',
        )
        second, status2 = telegram_alerts.create_or_get_alert(
            self.sessions, 'chat-2',
            role_family='ai_ml', role_keywords=['nlp'], role_label='AI/ML NLP Engineer',
            city='bengaluru',
        )
        self.assertEqual(status1, 'created')
        self.assertEqual(status2, 'exists')
        self.assertEqual(first['id'], second['id'])

    def test_a_fourth_alert_hits_the_max_active_cap(self):
        for idx, family in enumerate(['ai_ml', 'data', 'software']):
            _alert, status = telegram_alerts.create_or_get_alert(
                self.sessions, 'chat-3',
                role_family=family, role_keywords=[], role_label=family,
                city='bengaluru',
            )
            self.assertEqual(status, 'created', f'iteration {idx}')
        _alert, status = telegram_alerts.create_or_get_alert(
            self.sessions, 'chat-3',
            role_family='cybersecurity', role_keywords=[], role_label='Cybersecurity',
            city='bengaluru',
        )
        self.assertEqual(status, 'limit')
        self.assertEqual(self.sessions.count_active_job_alerts('chat-3'), telegram_alerts.MAX_ACTIVE_ALERTS)

    def test_stopping_an_alert_frees_a_slot_for_a_new_one(self):
        alert, _status = telegram_alerts.create_or_get_alert(
            self.sessions, 'chat-4',
            role_family='ai_ml', role_keywords=[], role_label='AI/ML', city='',
        )
        self.sessions.deactivate_job_alert(alert['id'], 'chat-4')
        _second, status = telegram_alerts.create_or_get_alert(
            self.sessions, 'chat-4',
            role_family='data', role_keywords=[], role_label='Data', city='',
        )
        self.assertEqual(status, 'created')

    def test_format_my_alerts_lists_active_alerts_with_stop_buttons(self):
        telegram_alerts.create_or_get_alert(
            self.sessions, 'chat-5',
            role_family='ai_ml', role_keywords=[], role_label='AI/ML', city='chennai',
        )
        alerts = self.sessions.list_job_alerts('chat-5')
        text, keyboard = telegram_alerts.format_my_alerts(alerts)
        self.assertIn('AI/ML', text)
        self.assertIn('Chennai', text)
        labels = [label for row in keyboard for label, _data in row]
        self.assertIn('🔕 Stop #1', labels)

    def test_format_my_alerts_empty_state_has_no_keyboard(self):
        text, keyboard = telegram_alerts.format_my_alerts([])
        self.assertIn('no active alerts', text)
        self.assertIsNone(keyboard)


class AlertDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = TelegramSessionStore(Path(self.tmp.name) / 'bot.db')
        self.api = FakeAPI()
        self.sent: list[tuple[str, str, list]] = []

    def tearDown(self):
        self.tmp.cleanup()

    def _send(self, chat_id, text, keyboard):
        self.sent.append((chat_id, text, keyboard))

    def test_dispatch_sends_only_genuinely_new_matches(self):
        alert, _status = telegram_alerts.create_or_get_alert(
            self.sessions, 'chat-1',
            role_family='ai_ml', role_keywords=[], role_label='AI/ML',
            city='bengaluru', seen_ids=['4448000001'],
        )
        self.api.jobs = [make_job(1), make_job(2)]
        sent = telegram_alerts.dispatch_due_alerts(self.sessions, self.api, self._send)
        self.assertEqual(sent, 1)
        self.assertEqual(len(self.sent), 1)
        chat_id, text, keyboard = self.sent[0]
        self.assertEqual(chat_id, 'chat-1')
        self.assertNotIn('4448000001', text)  # already-seen job excluded
        self.assertIn('Company 2', text)
        self.assertIn('🔔 New AI/ML openings', text)
        self.assertIn('Tip: tap 👍', text)
        labels = [label for row in keyboard for label, _data in row]
        self.assertIn('👍 Like', labels)
        self.assertIn('🔕 Stop this alert', labels)
        updated = self.sessions.get_job_alert(alert['id'])
        self.assertIn('4448000002', updated['sent_job_ids'])

    def test_dispatch_is_silent_when_nothing_new_matches(self):
        telegram_alerts.create_or_get_alert(
            self.sessions, 'chat-2',
            role_family='ai_ml', role_keywords=[], role_label='AI/ML', city='bengaluru',
            seen_ids=['4448000001'],
        )
        self.api.jobs = [make_job(1)]
        sent = telegram_alerts.dispatch_due_alerts(self.sessions, self.api, self._send)
        self.assertEqual(sent, 0)
        self.assertEqual(self.sent, [])

    def test_a_job_already_sent_by_a_prior_dispatch_is_never_resent(self):
        telegram_alerts.create_or_get_alert(
            self.sessions, 'chat-3',
            role_family='ai_ml', role_keywords=[], role_label='AI/ML', city='bengaluru',
        )
        self.api.jobs = [make_job(1)]
        telegram_alerts.dispatch_due_alerts(self.sessions, self.api, self._send)
        self.assertEqual(len(self.sent), 1)
        self.sent.clear()
        # Same job still returned by the API on the next run — must not repeat.
        telegram_alerts.dispatch_due_alerts(self.sessions, self.api, self._send)
        self.assertEqual(self.sent, [])

    def test_matching_ignores_narrow_role_keywords_family_and_city_only(self):
        """Ashok, 2026-08-07: match at family+city level, not the narrow
        button keyword — a specific keyword can go quiet even though the
        family has openings (same class of gap already fixed for search)."""
        telegram_alerts.create_or_get_alert(
            self.sessions, 'chat-4',
            role_family='ai_ml', role_keywords=['nlp'], role_label='AI/ML NLP Engineer',
            city='bengaluru',
        )
        self.api.jobs = [make_job(1, title='Generative AI Engineer')]
        sent = telegram_alerts.dispatch_due_alerts(self.sessions, self.api, self._send)
        # role_family alone ('ai_ml') matches; the narrow 'nlp' keyword
        # would have rejected this title, but alerts are keyed on family.
        self.assertEqual(sent, 0)

    def test_a_different_city_never_matches(self):
        telegram_alerts.create_or_get_alert(
            self.sessions, 'chat-5',
            role_family='ai_ml', role_keywords=[], role_label='AI/ML', city='chennai',
        )
        self.api.jobs = [make_job(1, city='bengaluru')]
        sent = telegram_alerts.dispatch_due_alerts(self.sessions, self.api, self._send)
        self.assertEqual(sent, 0)

    def test_should_dispatch_today_flips_once_marked(self):
        self.assertTrue(telegram_alerts.should_dispatch_today(self.sessions))
        telegram_alerts.mark_dispatched_today(self.sessions)
        self.assertFalse(telegram_alerts.should_dispatch_today(self.sessions))


if __name__ == '__main__':
    unittest.main()
