"""Guided onboarding + guest profile management for JobMaster.

Covers the flow Ashok specified: a bare greeting starts a gradual,
deterministic conversation — job role, then experience (with a grounded
"today" count shown first), then city preference — ending in a real,
grounded job listing plus a forward-looking suggestion. Also covers the
accompanying guest-management surface (`/guestprofile`) that lets Ashok see
what a guest last searched for.

These are new capability tests, not part of the JM-* validation corpus yet;
IDs will be assigned to `documents/jobmaster-telegram-validation.md` once
Ashok runs the flow live in Telegram.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import telegram_guests
from app.telegram_job_search import IntentInterpreter, JobMasterEngine
from app.telegram_sessions import AmbiguousTelegramIdentity, TelegramSessionStore
from scripts.telegram_job_bot import JobMasterTelegramBot
from tests.test_jobmaster_acceptance import FakeAPI, make_job


class BaseOnboardingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = TelegramSessionStore(Path(self.tmp.name) / 'sessions.db')
        self.api = FakeAPI()
        self.engine = JobMasterEngine(
            api_get=self.api,
            interpreter=IntentInterpreter(enabled=False),
            sessions=self.sessions,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _set_today_count(self, count: int, *, city: str | None = None) -> None:
        self.api.insights[city or 'all'] = {
            'total': count, 'prior_total': 0, 'companies': [], 'roles': [],
        }


class GreetingStartsOnboardingTests(BaseOnboardingTest):
    def test_bare_hi_asks_for_a_role_not_unfiltered_jobs(self):
        reply = self.engine.handle('Hi', 'chat-1')
        self.assertIn('role', reply.lower())
        self.assertIn('JobMaster', reply)
        for job in self.api.jobs:
            self.assertNotIn(job['company'], reply)

    def test_common_greeting_variants_all_trigger_onboarding(self):
        for text in ('hello', 'Hey!', 'heya', 'good morning', 'Namaste', 'yo'):
            with self.subTest(text=text):
                fresh = JobMasterEngine(
                    api_get=FakeAPI(),
                    interpreter=IntentInterpreter(enabled=False),
                    sessions=TelegramSessionStore(Path(self.tmp.name) / f'{text}.db'),
                )
                reply = fresh.handle(text, 'chat-x')
                self.assertIn('role', reply.lower())

    def test_fully_specified_first_message_is_not_hijacked_by_onboarding(self):
        reply = self.engine.handle('AI jobs in Bangalore for fresher', 'chat-2')
        self.assertNotIn('What job role', reply)
        self.assertTrue(reply.startswith('1.'))

    def test_bare_jobs_keyword_still_returns_unfiltered_results_not_onboarding(self):
        # JM-080 contract: a contentless-but-not-a-greeting query still
        # returns broad results immediately; onboarding must not widen scope
        # beyond literal greetings.
        reply = self.engine.handle('jobs', 'chat-3')
        self.assertTrue(reply.startswith('1.'))


class OnboardingFlowTests(BaseOnboardingTest):
    def test_full_role_experience_city_flow_reaches_grounded_results(self):
        self.api.jobs = [make_job(i, city='chennai') for i in range(1, 4)]
        self._set_today_count(3)
        self.engine.handle('Hi', 'chat-10')
        experience_prompt = self.engine.handle('AI Engineer', 'chat-10')
        self.assertIn('3', experience_prompt)
        self.assertIn('experience', experience_prompt.lower())
        city_prompt = self.engine.handle('fresher', 'chat-10')
        self.assertIn('city', city_prompt.lower())
        final = self.engine.handle('Chennai', 'chat-10')
        self.assertTrue(final.startswith('1.'))
        self.assertIn('Company 1', final)
        self.assertIn('linkedin.com', final)
        self.assertIn('Tell me a new role or city', final)

    def test_zero_count_role_reasks_role_instead_of_dead_ending(self):
        self._set_today_count(0)
        self.engine.handle('Hi', 'chat-11')
        reply = self.engine.handle('Astronaut trainer', 'chat-11')
        self.assertIn('different role', reply.lower())
        onboarding = self.sessions.load_onboarding('chat-11')
        self.assertEqual(onboarding['stage'], 'ask_role')

    def test_role_answer_with_no_role_words_asks_again(self):
        self.engine.handle('Hi', 'chat-12')
        reply = self.engine.handle('!!!', 'chat-12')
        self.assertIn("didn't catch a job role", reply)
        onboarding = self.sessions.load_onboarding('chat-12')
        self.assertEqual(onboarding['stage'], 'ask_role')

    def test_skip_word_for_experience_and_city_removes_filters(self):
        self._set_today_count(5)
        self.engine.handle('Hi', 'chat-13')
        self.engine.handle('Java Developer', 'chat-13')
        self.engine.handle('any', 'chat-13')
        final = self.engine.handle('any', 'chat-13')
        saved = self.sessions.load_search('chat-13')
        intent_dict = saved[0]
        self.assertEqual(intent_dict['experience'], '')
        self.assertEqual(intent_dict['cities'], [])
        self.assertTrue(final.startswith('1.') or 'No verified jobs' in final)

    def test_unrecognized_experience_falls_back_gracefully_and_still_asks_city(self):
        self._set_today_count(2)
        self.engine.handle('Hi', 'chat-14')
        self.engine.handle('Data Analyst', 'chat-14')
        reply = self.engine.handle('a long time', 'chat-14')
        self.assertIn("couldn't match an experience level", reply)
        self.assertIn('city', reply.lower())

    def test_unrecognized_city_falls_back_gracefully_and_finishes(self):
        self._set_today_count(2)
        self.engine.handle('Hi', 'chat-15')
        self.engine.handle('Data Analyst', 'chat-15')
        self.engine.handle('fresher', 'chat-15')
        reply = self.engine.handle('Mars', 'chat-15')
        self.assertIn("couldn't match a city", reply)
        self.assertIsNone(self.sessions.load_onboarding('chat-15'))

    def test_eager_role_answer_skips_ahead_past_already_answered_slots(self):
        self.api.jobs = [make_job(i, city='chennai') for i in range(1, 4)]
        self._set_today_count(3)
        self.engine.handle('Hi', 'chat-16')
        reply = self.engine.handle('AI Engineer, fresher, in Chennai', 'chat-16')
        self.assertTrue(reply.startswith('1.'))
        self.assertIsNone(self.sessions.load_onboarding('chat-16'))

    def test_reset_mid_onboarding_clears_state(self):
        self.engine.handle('Hi', 'chat-17')
        self.engine.handle('/new', 'chat-17')
        self.assertIsNone(self.sessions.load_onboarding('chat-17'))

    def test_more_after_onboarding_completion_paginates_normally(self):
        self.api.jobs = [make_job(i) for i in range(1, 26)]
        self._set_today_count(25)
        self.engine.handle('Hi', 'chat-18')
        self.engine.handle('Machine Learning Engineer', 'chat-18')
        self.engine.handle('any', 'chat-18')
        first = self.engine.handle('any', 'chat-18')
        self.assertIn('Reply more', first)
        second = self.engine.handle('more', 'chat-18')
        self.assertIn('11.', second)

    def test_owner_and_guest_get_identical_onboarding_copy(self):
        owner_engine = JobMasterEngine(
            api_get=FakeAPI(),
            interpreter=IntentInterpreter(enabled=False),
            sessions=TelegramSessionStore(Path(self.tmp.name) / 'owner.db'),
        )
        guest_reply = self.engine.handle('Hi', 'guest-1')
        owner_reply = owner_engine.handle('Hi', 'owner-1')
        self.assertEqual(guest_reply, owner_reply)


class GuestProfilePersistenceTests(BaseOnboardingTest):
    def test_finishing_onboarding_saves_a_retrievable_profile(self):
        self.api.jobs = [make_job(i, city='chennai') for i in range(1, 4)]
        self._set_today_count(3)
        self.engine.handle('Hi', 'chat-20')
        self.engine.handle('AI Engineer', 'chat-20')
        self.engine.handle('fresher', 'chat-20')
        self.engine.handle('Chennai', 'chat-20')
        profile = self.sessions.get_guest_profile('chat-20')
        self.assertIsNotNone(profile)
        self.assertEqual(profile['role_family'], 'ai_ml')
        self.assertEqual(profile['experience'], 'fresher')
        self.assertEqual(profile['city'], 'chennai')

    def test_unknown_chat_has_no_profile(self):
        self.assertIsNone(self.sessions.get_guest_profile('never-chatted'))


class GuestProfileOwnerCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = TelegramSessionStore(Path(self.tmp.name) / 'bot.db')
        self.guests_patch = patch.object(
            telegram_guests, 'GUESTS_FILE', Path(self.tmp.name) / 'guests.json',
        )
        self.env_patch = patch.object(
            telegram_guests, 'HERMES_ENV', Path(self.tmp.name) / 'hermes.env',
        )
        self.guests_patch.start()
        self.env_patch.start()

        class _StubEngine:
            def handle(self, text, chat_id, **_kwargs):
                return 'stub'

        class _RecordingTelegramAPI:
            def __init__(self):
                self.sent: list[tuple[str, str]] = []

            def send(self, chat_id, text):
                self.sent.append((chat_id, text))

            def call(self, method, data=None, timeout=35):
                return {'ok': True}

        self.api = _RecordingTelegramAPI()
        self.bot = JobMasterTelegramBot(
            self.api,
            engine=_StubEngine(),
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )

    def tearDown(self):
        self.env_patch.stop()
        self.guests_patch.stop()
        self.tmp.cleanup()

    def test_owner_can_read_a_stored_guest_profile(self):
        self.sessions.save_guest_profile(
            '555',
            role_label='AI/ML',
            role_family='ai_ml',
            role_keywords=[],
            experience='fresher',
            city='chennai',
        )
        self.bot.process('owner', '/guestprofile 555')
        reply = self.api.sent[-1][1]
        self.assertIn('GUEST PROFILE', reply)
        self.assertIn('AI/ML', reply)
        self.assertIn('fresher', reply)

    def test_missing_profile_gives_an_honest_reply(self):
        self.bot.process('owner', '/guestprofile 999999')
        self.assertIn('No stored preferences', self.api.sent[-1][1])

    def test_guest_cannot_run_guestprofile_command(self):
        self.sessions.save_guest_profile('555', role_label='AI/ML')
        acked = self.bot._pre_ack('guest', '/guestprofile 555')
        self.bot.process('guest', '/guestprofile 555', acked=acked)
        self.assertFalse(acked)
        self.assertNotIn('AI/ML', self.api.sent[-1][1])

    def test_ambiguous_username_fails_closed(self):
        self.sessions.record_conversation(1, '111', 'sameuser', 'q1', 'a1')
        self.sessions.record_conversation(2, '222', 'sameuser', 'q2', 'a2')
        with self.assertRaises(AmbiguousTelegramIdentity):
            self.sessions.get_guest_profile('@sameuser')
        self.bot.process('owner', '/guestprofile @sameuser')
        self.assertIn('more than one Telegram account', self.api.sent[-1][1])


if __name__ == '__main__':
    unittest.main()
