"""Button-flow wizard tests — Family -> Role -> Experience -> City -> Results,
plus the non-focus experience -> waitlist-email branch. Ashok's spec
(2026-08-06): GTM only for Intern/Fresher; every other experience band gets
a static 'coming soon' message and an email capture instead of a search."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import telegram_waitlist
from app.job_role_families import title_matches_role_family
from app.telegram_buttons import (
    CITY_BUTTONS,
    EXPERIENCE_BUTTONS,
    FAMILY_BUTTONS,
    ROLE_BUTTONS,
    WINDOW_BUTTONS,
    ButtonFlow,
)
from app.telegram_job_search import IntentInterpreter, JobMasterEngine
from app.telegram_sessions import TelegramSessionStore


def make_job(i: int, *, title: str = 'Machine Learning Engineer', city: str = 'bengaluru') -> dict:
    job_id = str(4448000000 + i)
    return {
        'id': i,
        'linkedin_job_id': job_id,
        'title': title,
        'company': f'Company {i}',
        'city_key': city,
        'experience_band': 'Fresher' if i % 2 else None,
        'source_track': 'fresher',
        'job_url': f'https://www.linkedin.com/jobs/view/broken-title-{job_id}/?tracking=x',
    }


class FakeAPI:
    """Minimal Watch Tower double — same contract as the other JobMaster
    test files (see test_telegram_job_search.py)."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.jobs: list[dict] = []

    def __call__(self, path: str, params: dict | None = None):
        self.calls.append((path, params or {}))
        if path == '/api/jobs':
            params = params or {}
            rows = list(self.jobs)
            if params.get('city'):
                rows = [row for row in rows if row.get('city_key') == params['city']]
            if params.get('role_family'):
                rows = [
                    row for row in rows
                    if title_matches_role_family(row.get('title'), params['role_family'])
                ]
            terms = str(params.get('title_terms') or '').split()
            if terms:
                rows = [
                    row for row in rows
                    if any(term in str(row.get('title') or '').lower() for term in terms)
                ]
            if 'days' in params and params.get('days') is not None:
                # Simulate real posting-freshness filtering: fixtures default
                # to "old" (999) unless a test explicitly tags a job fresh
                # via _days_old, so a 'days' filter can genuinely zero out a
                # search (used to test the window-relax fallback).
                window = int(params['days'])
                rows = [row for row in rows if int(row.get('_days_old', 999)) <= window]
            offset = int(params.get('offset') or 0)
            limit = int(params.get('limit') or len(rows))
            return rows[offset:offset + limit]
        if path == '/api/jobs/insights':
            return {'total': 0, 'prior_total': 0, 'companies': [], 'roles': []}
        return {}


def _flatten(keyboard) -> list[tuple[str, str]]:
    return [button for row in (keyboard or []) for button in row]


class BaseButtonFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.api = FakeAPI()
        self.sessions = TelegramSessionStore(Path(self.tmp.name) / 'bot.db')
        self.engine = JobMasterEngine(
            api_get=self.api,
            interpreter=IntentInterpreter(enabled=False),
            sessions=self.sessions,
        )
        self.flow = ButtonFlow(self.engine)
        self.waitlist_patch = patch.object(
            telegram_waitlist, 'WAITLIST_FILE', Path(self.tmp.name) / 'waitlist.json',
        )
        self.waitlist_patch.start()

    def tearDown(self):
        self.waitlist_patch.stop()
        self.tmp.cleanup()


class FamilyRoleExperienceNavigationTests(BaseButtonFlowTest):
    def test_start_shows_all_seven_families_for_a_fresh_guest(self):
        reply = self.flow.start('chat-1')
        labels = [label for label, _data in _flatten(reply.keyboard)]
        for label, _key in FAMILY_BUTTONS:
            self.assertIn(label, labels)

    def test_picking_a_family_shows_its_role_buttons_and_a_back_button(self):
        reply = self.flow.handle_callback('chat-2', 'fam:software')
        labels = [label for label, _data in _flatten(reply.keyboard)]
        for label, _kw in ROLE_BUTTONS['software']:
            self.assertIn(label, labels)
        self.assertIn('◀ Back', labels)
        state = self.sessions.load_onboarding('chat-2')
        self.assertEqual(state['stage'], 'btn_role')
        self.assertEqual(state['role_family'], 'software')

    def test_picking_a_role_shows_all_five_experience_buttons(self):
        self.flow.handle_callback('chat-3', 'fam:software')
        reply = self.flow.handle_callback('chat-3', 'role:software:0')  # Java Developer
        labels = [label for label, _data in _flatten(reply.keyboard)]
        for label, _code in EXPERIENCE_BUTTONS:
            self.assertIn(label, labels)
        state = self.sessions.load_onboarding('chat-3')
        self.assertEqual(state['role_keywords'], ['java'])

    def test_back_from_role_screen_returns_to_family_list(self):
        self.flow.handle_callback('chat-4', 'fam:data')
        reply = self.flow.handle_callback('chat-4', 'back:family')
        labels = [label for label, _data in _flatten(reply.keyboard)]
        self.assertIn('AI/ML', labels)

    def test_back_from_window_screen_returns_to_the_experience_choices(self):
        # Fixed 2026-08-07 while inserting the posting-window step: every
        # other back button returns to the exact previous screen (back:family
        # -> family, back:role -> role) — back:experience must do the same
        # (return to the experience choices), not skip past it to role.
        self.flow.handle_callback('chat-5', 'fam:data')
        self.flow.handle_callback('chat-5', 'role:data:0')
        self.flow.handle_callback('chat-5', 'exp:fresher')
        reply = self.flow.handle_callback('chat-5', 'back:experience')
        labels = [label for label, _data in _flatten(reply.keyboard)]
        for label, _code in EXPERIENCE_BUTTONS:
            self.assertIn(label, labels)

    def test_back_from_city_screen_returns_to_the_window_choices(self):
        self.flow.handle_callback('chat-5b', 'fam:data')
        self.flow.handle_callback('chat-5b', 'role:data:0')
        self.flow.handle_callback('chat-5b', 'exp:fresher')
        self.flow.handle_callback('chat-5b', 'window:0')
        reply = self.flow.handle_callback('chat-5b', 'back:window')
        labels = [label for label, _data in _flatten(reply.keyboard)]
        for label, _code in WINDOW_BUTTONS:
            self.assertIn(label, labels)

    def test_unknown_or_stale_callback_never_leaves_a_dead_end(self):
        reply = self.flow.handle_callback('chat-6', 'role:software:99')
        # Falls back to re-showing the role list rather than crashing.
        labels = [label for label, _data in _flatten(reply.keyboard)]
        self.assertTrue(labels)


class FocusExperienceReachesWindowCityAndResultsTests(BaseButtonFlowTest):
    def test_fresher_experience_shows_window_buttons(self):
        self.flow.handle_callback('chat-10', 'fam:software')
        self.flow.handle_callback('chat-10', 'role:software:0')
        reply = self.flow.handle_callback('chat-10', 'exp:fresher')
        labels = [label for label, _data in _flatten(reply.keyboard)]
        for label, _code in WINDOW_BUTTONS:
            self.assertIn(label, labels)

    def test_intern_experience_also_reaches_window_step(self):
        self.flow.handle_callback('chat-11', 'fam:software')
        self.flow.handle_callback('chat-11', 'role:software:0')
        reply = self.flow.handle_callback('chat-11', 'exp:intern')
        labels = [label for label, _data in _flatten(reply.keyboard)]
        self.assertIn('Last 24 hours', labels)

    def test_picking_a_window_then_shows_city_buttons(self):
        self.flow.handle_callback('chat-10b', 'fam:software')
        self.flow.handle_callback('chat-10b', 'role:software:0')
        self.flow.handle_callback('chat-10b', 'exp:fresher')
        reply = self.flow.handle_callback('chat-10b', 'window:0')
        labels = [label for label, _data in _flatten(reply.keyboard)]
        for label, _key in CITY_BUTTONS:
            self.assertIn(label, labels)

    def test_picking_a_window_then_a_city_sends_the_days_param_to_the_api(self):
        self.api.jobs = [
            {**make_job(i, title='Java Developer', city='bengaluru'), '_days_old': 0}
            for i in range(1, 4)
        ]
        self.flow.handle_callback('chat-10c', 'fam:software')
        self.flow.handle_callback('chat-10c', 'role:software:0')
        self.flow.handle_callback('chat-10c', 'exp:fresher')
        self.flow.handle_callback('chat-10c', 'window:2')  # "Last 2 days"
        bengaluru_idx = next(i for i, (_l, key) in enumerate(CITY_BUTTONS) if key == 'bengaluru')
        self.flow.handle_callback('chat-10c', f'city:{bengaluru_idx}')
        job_calls = [params for path, params in self.api.calls if path == '/api/jobs']
        self.assertTrue(job_calls)
        self.assertTrue(all(params.get('days') == 2 for params in job_calls))

    def test_any_time_sends_no_days_param(self):
        self.api.jobs = [make_job(1, title='Java Developer', city='bengaluru')]
        self.flow.handle_callback('chat-10d', 'fam:software')
        self.flow.handle_callback('chat-10d', 'role:software:0')
        self.flow.handle_callback('chat-10d', 'exp:fresher')
        self.flow.handle_callback('chat-10d', 'window:')  # "Any time"
        any_idx = next(i for i, (_l, key) in enumerate(CITY_BUTTONS) if key == '')
        self.flow.handle_callback('chat-10d', f'city:{any_idx}')
        job_calls = [params for path, params in self.api.calls if path == '/api/jobs']
        self.assertTrue(job_calls)
        self.assertTrue(all('days' not in params for params in job_calls))

    def test_a_dead_end_time_window_falls_back_to_any_time(self):
        """Same 'never dead-end a guest' philosophy as the narrow-role
        fallback: a live job exists, but not within the aggressive 24h
        window the guest picked — show it anyway rather than 'No verified
        jobs'."""
        self.api.jobs = [make_job(1, title='Java Developer', city='bengaluru')]
        self.flow.handle_callback('chat-10e', 'fam:software')
        self.flow.handle_callback('chat-10e', 'role:software:0')
        self.flow.handle_callback('chat-10e', 'exp:fresher')
        self.flow.handle_callback('chat-10e', 'window:0')  # "Last 24 hours"
        any_idx = next(i for i, (_l, key) in enumerate(CITY_BUTTONS) if key == '')
        reply = self.flow.handle_callback('chat-10e', f'city:{any_idx}')
        self.assertNotIn('No verified jobs', reply.text)
        self.assertIn('No openings in that time window', reply.text)
        self.assertIn('Company 1', reply.text)

    def test_picking_a_city_runs_a_real_grounded_search(self):
        self.api.jobs = [make_job(i, title='Java Developer', city='bengaluru') for i in range(1, 4)]
        self.flow.handle_callback('chat-12', 'fam:software')
        self.flow.handle_callback('chat-12', 'role:software:0')
        self.flow.handle_callback('chat-12', 'exp:fresher')
        bengaluru_idx = next(i for i, (_l, key) in enumerate(CITY_BUTTONS) if key == 'bengaluru')
        reply = self.flow.handle_callback('chat-12', f'city:{bengaluru_idx}')
        self.assertTrue(reply.text.startswith('1.'))
        self.assertIn('Company 1', reply.text)
        self.assertIsNone(self.sessions.load_onboarding('chat-12'))

    def test_results_screen_offers_a_new_search_button(self):
        self.api.jobs = [make_job(1, title='Java Developer', city='bengaluru')]
        self.flow.handle_callback('chat-13', 'fam:software')
        self.flow.handle_callback('chat-13', 'role:software:0')
        self.flow.handle_callback('chat-13', 'exp:fresher')
        any_idx = next(i for i, (_l, key) in enumerate(CITY_BUTTONS) if key == '')
        reply = self.flow.handle_callback('chat-13', f'city:{any_idx}')
        labels = [label for label, _data in _flatten(reply.keyboard)]
        self.assertIn('🔄 New search', labels)

    def test_results_screen_also_offers_a_set_alert_button(self):
        self.api.jobs = [make_job(1, title='Java Developer', city='bengaluru')]
        self.flow.handle_callback('chat-13b', 'fam:software')
        self.flow.handle_callback('chat-13b', 'role:software:0')
        self.flow.handle_callback('chat-13b', 'exp:fresher')
        any_idx = next(i for i, (_l, key) in enumerate(CITY_BUTTONS) if key == '')
        reply = self.flow.handle_callback('chat-13b', f'city:{any_idx}')
        labels = [label for label, _data in _flatten(reply.keyboard)]
        self.assertIn('🔔 Set alert', labels)

    def test_zero_result_search_offers_try_another_role_or_family(self):
        self.api.jobs = []
        self.flow.handle_callback('chat-14', 'fam:software')
        self.flow.handle_callback('chat-14', 'role:software:0')
        self.flow.handle_callback('chat-14', 'exp:fresher')
        any_idx = next(i for i, (_l, key) in enumerate(CITY_BUTTONS) if key == '')
        reply = self.flow.handle_callback('chat-14', f'city:{any_idx}')
        self.assertIn('No verified jobs', reply.text)
        labels = [label for label, _data in _flatten(reply.keyboard)]
        self.assertIn('Try another role', labels)
        self.assertIn('Try another family', labels)

    def test_a_narrow_role_with_zero_openings_falls_back_to_the_wider_family(self):
        """Live regression (2026-08-06): Ashok picked AI/ML -> NLP Engineer
        -> Fresher -> a city and got a dead 'No verified jobs' screen even
        though the AI/ML family had openings — a narrow role button should
        never dead-end a guest when the wider, still-honest, same-family
        search has real results."""
        self.api.jobs = [make_job(1, title='Machine Learning Engineer', city='bengaluru')]
        self.flow.handle_callback('chat-16', 'fam:ai_ml')
        # ROLE_BUTTONS['ai_ml'][1] == ('NLP Engineer', ['nlp']) — no job in
        # the fixture has "nlp" in its title, but the family itself does.
        self.flow.handle_callback('chat-16', 'role:ai_ml:1')
        self.flow.handle_callback('chat-16', 'exp:fresher')
        bengaluru_idx = next(i for i, (_l, key) in enumerate(CITY_BUTTONS) if key == 'bengaluru')
        reply = self.flow.handle_callback('chat-16', f'city:{bengaluru_idx}')
        self.assertNotIn('No verified jobs', reply.text)
        self.assertIn('No AI/ML NLP openings right now', reply.text)
        self.assertIn('here are other AI/ML roles instead', reply.text)
        self.assertIn('Company 1', reply.text)
        labels = [label for label, _data in _flatten(reply.keyboard)]
        self.assertIn('🔄 New search', labels)
        # The guest's actual pick (NLP Engineer) is what gets remembered for
        # "welcome back" — not the broadened search that was shown instead.
        profile = self.sessions.get_guest_profile('chat-16')
        self.assertEqual(profile['role_keywords'], ['nlp'])

    def test_more_button_reuses_the_existing_pagination_engine(self):
        self.api.jobs = [make_job(i, title='Java Developer', city='bengaluru') for i in range(1, 26)]
        self.flow.handle_callback('chat-15', 'fam:software')
        self.flow.handle_callback('chat-15', 'role:software:0')
        self.flow.handle_callback('chat-15', 'exp:fresher')
        any_idx = next(i for i, (_l, key) in enumerate(CITY_BUTTONS) if key == '')
        self.flow.handle_callback('chat-15', f'city:{any_idx}')
        reply = self.flow.handle_callback('chat-15', 'more')
        self.assertIn('11.', reply.text)

    def test_typing_more_after_a_button_search_also_works(self):
        """The old text pagination command stays a working shortcut even
        after a button-driven search — same search_sessions table."""
        self.api.jobs = [make_job(i, title='Java Developer', city='bengaluru') for i in range(1, 26)]
        self.flow.handle_callback('chat-16', 'fam:software')
        self.flow.handle_callback('chat-16', 'role:software:0')
        self.flow.handle_callback('chat-16', 'exp:fresher')
        any_idx = next(i for i, (_l, key) in enumerate(CITY_BUTTONS) if key == '')
        self.flow.handle_callback('chat-16', f'city:{any_idx}')
        second = self.engine.handle('more', 'chat-16')
        self.assertIn('11.', second)

    def test_completed_search_saves_a_guest_profile_with_chosen_experience_word(self):
        self.api.jobs = [make_job(1, title='Java Developer', city='bengaluru')]
        self.flow.handle_callback('chat-17', 'fam:software')
        self.flow.handle_callback('chat-17', 'role:software:0')
        self.flow.handle_callback('chat-17', 'exp:intern')
        any_idx = next(i for i, (_l, key) in enumerate(CITY_BUTTONS) if key == '')
        self.flow.handle_callback('chat-17', f'city:{any_idx}')
        profile = self.sessions.get_guest_profile('chat-17')
        self.assertEqual(profile['experience'], 'intern')
        self.assertEqual(profile['role_family'], 'software')


class SetAlertButtonTests(BaseButtonFlowTest):
    """"Set alert every day" (Ashok, 2026-08-07): a button right next to
    the results actions row that subscribes the guest to daily matches for
    the exact search they just ran."""

    def _run_to_results(self, chat_id: str, *, city_idx: int | None = None) -> None:
        self.flow.handle_callback(chat_id, 'fam:ai_ml')
        self.flow.handle_callback(chat_id, 'role:ai_ml:0')
        self.flow.handle_callback(chat_id, 'exp:fresher')
        idx = city_idx if city_idx is not None else next(
            i for i, (_l, key) in enumerate(CITY_BUTTONS) if key == 'bengaluru'
        )
        self.flow.handle_callback(chat_id, f'city:{idx}')

    def test_tapping_set_alert_creates_a_subscription(self):
        self.api.jobs = [make_job(1, title='Machine Learning Engineer', city='bengaluru')]
        self._run_to_results('chat-alert-1')
        reply = self.flow.handle_callback('chat-alert-1', 'alert:set')
        self.assertIn('🔔 Alert set', reply.text)
        alerts = self.sessions.list_job_alerts('chat-alert-1')
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['city'], 'bengaluru')

    def test_setting_the_same_alert_twice_says_it_is_already_on(self):
        self.api.jobs = [make_job(1, title='Machine Learning Engineer', city='bengaluru')]
        self._run_to_results('chat-alert-2')
        self.flow.handle_callback('chat-alert-2', 'alert:set')
        reply = self.flow.handle_callback('chat-alert-2', 'alert:set')
        self.assertIn('already ON', reply.text)
        self.assertEqual(len(self.sessions.list_job_alerts('chat-alert-2')), 1)

    def test_alert_seeds_already_seen_jobs_so_they_are_never_re_alerted(self):
        self.api.jobs = [make_job(i, title='Machine Learning Engineer', city='bengaluru') for i in range(1, 3)]
        self._run_to_results('chat-alert-3')
        self.flow.handle_callback('chat-alert-3', 'alert:set')
        alert = self.sessions.list_job_alerts('chat-alert-3')[0]
        self.assertTrue(alert['sent_job_ids'])

    def test_a_fourth_alert_is_refused_with_the_cap_message(self):
        chat = 'chat-alert-cap'
        for family in ('ai_ml', 'data', 'software'):
            self.flow.handle_callback(chat, f'fam:{family}')
            self.flow.handle_callback(chat, f'role:{family}:0')
            self.flow.handle_callback(chat, 'exp:fresher')
            any_idx = next(i for i, (_l, key) in enumerate(CITY_BUTTONS) if key == '')
            self.flow.handle_callback(chat, f'city:{any_idx}')
            self.flow.handle_callback(chat, 'alert:set')
        self.flow.handle_callback(chat, 'fam:design')
        self.flow.handle_callback(chat, 'role:design:0')
        self.flow.handle_callback(chat, 'exp:fresher')
        any_idx = next(i for i, (_l, key) in enumerate(CITY_BUTTONS) if key == '')
        self.flow.handle_callback(chat, f'city:{any_idx}')
        reply = self.flow.handle_callback(chat, 'alert:set')
        self.assertIn('/myalerts', reply.text)
        self.assertEqual(len(self.sessions.list_job_alerts(chat)), 3)

    def test_tapping_set_alert_with_no_prior_search_is_handled_gracefully(self):
        reply = self.flow.handle_callback('chat-alert-none', 'alert:set')
        self.assertIn('Search for a role first', reply.text)


class BroadcastStartRecordingTests(BaseButtonFlowTest):
    def test_start_registers_the_chat_as_a_broadcast_subscriber(self):
        self.flow.start('chat-bc-1')
        self.assertEqual(self.sessions.list_active_broadcast_subscribers(), ['chat-bc-1'])


class NonFocusExperienceWaitlistTests(BaseButtonFlowTest):
    def test_experienced_band_shows_coming_soon_and_no_search_runs(self):
        self.flow.handle_callback('chat-20', 'fam:data')
        self.flow.handle_callback('chat-20', 'role:data:0')
        reply = self.flow.handle_callback('chat-20', 'exp:5-10')
        self.assertIn('coming soon', reply.text.lower())
        self.assertIn('email', reply.text.lower())
        self.assertEqual(len(self.api.calls), 0)  # never touches the Tower API

    def test_valid_email_is_captured_and_confirmed(self):
        self.flow.handle_callback('chat-21', 'fam:data')
        self.flow.handle_callback('chat-21', 'role:data:0')
        self.flow.handle_callback('chat-21', 'exp:10plus')
        reply = self.flow.handle_text('chat-21', 'student@example.com')
        self.assertIsNotNone(reply)
        self.assertIn('student@example.com', reply.text)
        entries = telegram_waitlist.list_waitlist()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['email'], 'student@example.com')
        self.assertEqual(entries[0]['experience'], '10plus')
        self.assertIsNone(self.sessions.load_onboarding('chat-21'))

    def test_invalid_email_is_rejected_and_asked_again(self):
        self.flow.handle_callback('chat-22', 'fam:data')
        self.flow.handle_callback('chat-22', 'role:data:0')
        self.flow.handle_callback('chat-22', 'exp:1-4')
        reply = self.flow.handle_text('chat-22', 'not-an-email')
        self.assertIn('valid email', reply.text)
        self.assertEqual(telegram_waitlist.waitlist_count(), 0)
        # Still waiting — a later, valid email in the same state still works.
        confirmed = self.flow.handle_text('chat-22', 'me@school.edu')
        self.assertIn('me@school.edu', confirmed.text)

    def test_skip_clears_the_waitlist_prompt_without_saving_anything(self):
        self.flow.handle_callback('chat-23', 'fam:data')
        self.flow.handle_callback('chat-23', 'role:data:0')
        self.flow.handle_callback('chat-23', 'exp:1-4')
        reply = self.flow.handle_text('chat-23', 'skip')
        self.assertIn('No worries', reply.text)
        self.assertEqual(telegram_waitlist.waitlist_count(), 0)
        self.assertIsNone(self.sessions.load_onboarding('chat-23'))

    def test_text_outside_the_waitlist_stage_is_not_consumed(self):
        """handle_text must return None (not a reply) for every stage except
        btn_waitlist_email, so the caller can fall through to the old
        free-text engine unchanged."""
        self.flow.handle_callback('chat-24', 'fam:data')
        result = self.flow.handle_text('chat-24', 'Data Analyst')
        self.assertIsNone(result)
        result_fresh = self.flow.handle_text('chat-25', 'Hi')
        self.assertIsNone(result_fresh)


class RestartAndWelcomeBackTests(BaseButtonFlowTest):
    def test_restart_clears_state_and_shows_family_buttons(self):
        self.flow.handle_callback('chat-30', 'fam:software')
        self.flow.handle_callback('chat-30', 'role:software:0')
        reply = self.flow.handle_callback('chat-30', 'restart')
        labels = [label for label, _data in _flatten(reply.keyboard)]
        self.assertIn('AI/ML', labels)
        self.assertIsNone(self.sessions.load_onboarding('chat-30'))

    def test_returning_guest_with_a_focus_profile_gets_a_welcome_back_prompt(self):
        self.sessions.save_guest_profile(
            'chat-31', role_label='Java Software', role_family='software',
            role_keywords=['java'], experience='fresher', city='bengaluru',
        )
        reply = self.flow.start('chat-31')
        labels = [label for label, _data in _flatten(reply.keyboard)]
        self.assertIn('Yes, same search', labels)
        self.assertIn('fresher', reply.text.lower())

    def test_saying_yes_repeats_the_exact_stored_search(self):
        self.api.jobs = [make_job(1, title='Java Developer', city='bengaluru')]
        self.sessions.save_guest_profile(
            'chat-32', role_label='Java Software', role_family='software',
            role_keywords=['java'], experience='fresher', city='bengaluru',
        )
        self.flow.start('chat-32')
        reply = self.flow.handle_callback('chat-32', 'wb_yes')
        self.assertTrue(reply.text.startswith('1.'))

    def test_saying_no_starts_a_fresh_family_pick(self):
        self.sessions.save_guest_profile(
            'chat-33', role_label='Java Software', role_family='software',
            role_keywords=['java'], experience='fresher', city='bengaluru',
        )
        self.flow.start('chat-33')
        reply = self.flow.handle_callback('chat-33', 'wb_no')
        labels = [label for label, _data in _flatten(reply.keyboard)]
        self.assertIn('AI/ML', labels)

    def test_a_stored_non_focus_profile_never_triggers_welcome_back(self):
        """A guest who only ever hit the waitlist path has no real search to
        recall — GTM focus means only Intern/Fresher profiles get one."""
        self.sessions.save_guest_profile(
            'chat-34', role_label='Data', role_family='data',
            role_keywords=[], experience='5-10', city='',
        )
        reply = self.flow.start('chat-34')
        labels = [label for label, _data in _flatten(reply.keyboard)]
        self.assertIn('AI/ML', labels)
        self.assertNotIn('Welcome back', reply.text)


if __name__ == '__main__':
    unittest.main()
