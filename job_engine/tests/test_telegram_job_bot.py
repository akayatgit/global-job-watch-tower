from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app import telegram_alerts, telegram_broadcast, telegram_guests
from app.telegram_buttons import BTN_PREFIX
from app.telegram_sessions import TelegramSessionStore
from scripts.telegram_job_bot import (
    JobMasterTelegramBot,
    _telegram_chunks,
    _utf16_units,
)


class FakeTelegramAPI:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.calls: list[tuple[str, dict]] = []
        self.keyboards_sent: list[tuple[str, str, list | None]] = []
        self.photos_sent: list[tuple[str, str, str, list | None]] = []

    def send(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))

    def send_keyboard(self, chat_id: str, text: str, keyboard: list | None) -> None:
        self.keyboards_sent.append((chat_id, text, keyboard))
        self.send(chat_id, text)

    def send_photo(
        self, chat_id: str, photo_file_id: str, caption: str = '', keyboard: list | None = None,
    ) -> None:
        self.photos_sent.append((chat_id, photo_file_id, caption, keyboard))

    def answer_callback(self, callback_query_id: str, text: str = '') -> None:
        pass

    def call(self, method: str, data: dict | None = None, timeout: int = 35) -> dict:
        self.calls.append((method, data or {}))
        return {'ok': True}


class FakeEngine:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.company_calls: list[tuple[str, int, str]] = []
        self.api_calls: list[tuple[str, dict | None]] = []
        self.reset_preview = {
            'jobs': 4120,
            'runs': 890,
            'request_logs': 3000,
            'companies': 310,
            'companies_watched_kept': 12,
            'companies_unwatched_wiped': 298,
            'enabled_searches': 55,
            'active_searches': ['MNC · Deloitte — Fresher'],
        }
        self.companies_roster: dict = {'total': 0, 'companies': []}
        self.funnel_data: dict = {
            'hours': 24,
            'caught': 42,
            'in_collection_cities': 30,
            'role_matched': 25,
            'detail_verified': 18,
            'servable_fresher': 7,
            'pending_verification': 24,
            'total_all_time': 500,
            'enabled_searches': 84,
            'runs_in_window': 60,
            'last_catch_at': '2026-08-19T04:00:00+00:00',
        }
        self.jobs_rows: list[dict] = [
            {
                'title': 'Data Analyst (Fresher)',
                'company': 'Deloitte',
                'city_key': None,
                'location': 'Bengaluru, Karnataka, India',
                'linkedin_job_id': '4448000301',
                'job_url': 'https://www.linkedin.com/jobs/view/4448000301/',
                'salary_text': 'INR 4,50,000 - 6,00,000 per annum',
            },
            {
                'title': 'SQL Developer — 0-1 years',
                'company': 'Oracle',
                'city_key': None,
                'location': 'Hyderabad, Telangana, India',
                'linkedin_job_id': '4448000302',
                'job_url': 'https://www.linkedin.com/jobs/view/4448000302/',
            },
        ]

    def handle(self, text: str, chat_id: str) -> str:
        self.calls.append((text, chat_id))
        if text == '/new':
            return 'Search reset. Send a role, city, or job-market question.'
        return '1. AI Engineer — Acme — Fresher\nhttps://www.linkedin.com/jobs/view/4448000001/'

    def api_get(self, path: str, params: dict | None = None):
        self.api_calls.append((path, params))
        if path == '/api/tower/reset-preview':
            return self.reset_preview
        if path == '/api/watchlist/companies':
            return self.companies_roster
        if path == '/api/jobs/funnel':
            return self.funnel_data
        if path == '/api/jobs':
            rows = list(self.jobs_rows)
            # Honour limit/offset so /topfreshers pagination tests exercise
            # the real paging loop against this fake.
            offset = int((params or {}).get('offset') or 0)
            limit = (params or {}).get('limit')
            if offset:
                rows = rows[offset:]
            if limit is not None:
                rows = rows[: int(limit)]
            return rows
        return {}

    def company_jobs(self, company: str, days: int, chat_id: str) -> str:
        self.company_calls.append((company, days, chat_id))
        return (
            f'{company.title()} — 3 openings posted in the last 7 days '
            '(5 this month · 2 caught in 24h)\n\n'
            '1. Audit Analyst — Fresher\nhttps://www.linkedin.com/jobs/view/4448000201/'
        )


class SmokeEngine:
    def __init__(self, valid: bool = True):
        self.valid = valid

    def handle(self, text: str, chat_id: str) -> str:
        if not self.valid:
            return 'JobMaster could not reach live Watch Tower data. Try again shortly.'
        return '\n\n'.join(
            f'{i}. AI Engineer {i} — Company {i} — Fresher\n'
            f'https://www.linkedin.com/jobs/view/{4448000000 + i}/'
            for i in range(1, 11)
        )


class FakeVoice:
    """Deterministic stand-in for VoiceLayer: prefixes every reply so tests
    can assert exactly where the wiring applies it (and where it must not)."""

    def __init__(self, prefix: str = 'VOICED::'):
        self.prefix = prefix
        self.calls: list[str] = []

    def speak(self, reply: str) -> str:
        self.calls.append(reply)
        return f'{self.prefix}{reply}'


class FailingTelegramAPI(FakeTelegramAPI):
    def send(self, chat_id: str, text: str) -> None:
        raise OSError('Telegram unavailable')


class FlakyTelegramAPI(FakeTelegramAPI):
    def __init__(self):
        super().__init__()
        self.failed_once = False

    def send(self, chat_id: str, text: str) -> None:
        if text.startswith('1. AI Engineer') and not self.failed_once:
            self.failed_once = True
            raise OSError('temporary send failure')
        super().send(chat_id, text)


class TelegramBotContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = TelegramSessionStore(Path(self.tmp.name) / 'bot.db')
        self.guests_patch = patch.object(
            telegram_guests,
            'GUESTS_FILE',
            Path(self.tmp.name) / 'guests.json',
        )
        self.env_patch = patch.object(
            telegram_guests,
            'HERMES_ENV',
            Path(self.tmp.name) / 'hermes.env',
        )
        self.guests_patch.start()
        self.env_patch.start()
        self.api = FakeTelegramAPI()
        self.engine = FakeEngine()
        self.bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'42'},
        )

    def tearDown(self):
        self.env_patch.stop()
        self.guests_patch.stop()
        self.tmp.cleanup()

    def test_thinking_is_immediate_before_result(self):
        self.bot.process('1221647274', 'Fresh AI jobs in Bangalore')
        self.assertEqual(self.api.sent[0], ('1221647274', 'Thinking…'))
        self.assertTrue(self.api.sent[1][1].startswith('1. AI Engineer'))

    def test_poll_loop_ack_is_not_duplicated_by_worker(self):
        acked = self.bot._pre_ack('1221647274', 'Fresh AI jobs in Bangalore')
        self.assertTrue(acked)
        self.bot.process('1221647274', 'Fresh AI jobs in Bangalore', acked=acked)
        self.assertEqual(
            [text for _chat, text in self.api.sent].count('Thinking…'),
            1,
        )

    def test_new_has_no_thinking_or_engine_metadata(self):
        self.bot.process('1221647274', '/new')
        self.assertEqual(len(self.api.sent), 1)
        text = self.api.sent[0][1]
        self.assertTrue(text.startswith('Search reset. Send a role, city, or job-market question.'))
        for banned in ('qwen', 'Provider', 'Endpoint', 'terminal', 'mcp__'):
            self.assertNotIn(banned, text)

    def test_every_sender_gets_same_interface(self):
        self.bot.process('owner', 'AI jobs Bangalore')
        self.bot._last_request.clear()
        self.bot.process('guest', 'AI jobs Bangalore')
        owner_reply = [text for chat, text in self.api.sent if chat == 'owner'][-1]
        guest_reply = [text for chat, text in self.api.sent if chat == 'guest'][-1]
        self.assertEqual(owner_reply, guest_reply)

    def test_same_chat_burst_is_throttled_after_first_result(self):
        self.bot.process('42', 'AI jobs Bangalore')
        self.bot.process('42', 'more')
        self.assertEqual(self.api.sent[-1], ('42', 'One request at a time.'))
        self.assertEqual(len(self.engine.calls), 1)

    def test_help_is_jobmaster_not_generic_assistant(self):
        # Guests keep the simple JobMaster line — never the ops sheet.
        self.bot.process('guest-77', '/help')
        self.assertEqual(
            self.api.sent[-1][1],
            'JobMaster provides verified jobs and live job-market insights. '
            'Ask naturally in any sentence.',
        )

    def test_owner_help_lists_every_command_with_options(self):
        # Chat '42' is the owner — /help shows the full command sheet.
        self.bot.process('42', '/help')
        text = self.api.sent[-1][1]
        self.assertIn('JOBMASTER · ALL COMMANDS', text)
        for fragment in (
            '/topfreshers [company:<name>] [skill:<term>] [role:<term>]',
            'city:<chennai/bangalore/remote>',
            '/companyjobs <company> [24h | 7 | 30]',
            '/addcompany <name>',
            '/history <@username or ID> [1–40]',
            '-unfiltered',
        ):
            self.assertIn(fragment, text)
        from scripts.telegram_job_bot import OWNER_MENU

        for item in OWNER_MENU:
            self.assertIn(f"/{item['command']}", text)

    def test_start_launches_the_button_flow_not_the_old_text_blurb(self):
        self.bot.process('42', '/start')
        self.assertIn('What kind of role are you looking for?', self.api.sent[-1][1])

    def test_owner_board_command_bypasses_job_search_engine(self):
        rendered: list[tuple[str, int | None]] = []

        def board_renderer(board: str, *, days: int | None = None) -> str:
            rendered.append((board, days))
            return 'TOWER HEALTH · 72°'

        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
            board_renderer=board_renderer,
        )
        bot.process('owner', '/health')
        self.assertEqual(self.api.sent, [('owner', 'TOWER HEALTH · 72°')])
        self.assertEqual(rendered, [('health', None)])
        self.assertEqual(self.engine.calls, [])

    def test_owner_hiring_signal_command_passes_window(self):
        rendered: list[tuple[str, int | None]] = []

        def board_renderer(board: str, *, days: int | None = None) -> str:
            rendered.append((board, days))
            return 'HIRING SIGNALS'

        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
            board_renderer=board_renderer,
        )
        bot.process('owner', '/hiringsignals 14')
        self.assertEqual(rendered, [('signals', 14)])

    def test_owner_stats_command_becomes_grounded_insight_query(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('owner', '/stats ai')
        self.assertEqual(
            self.engine.calls,
            [('How many ai jobs in the past 24 hours?', 'owner')],
        )
        self.assertNotIn('Thinking…', [text for _chat, text in self.api.sent])

    def test_owner_companyjobs_routes_to_engine_with_window(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('owner', '/companyjobs deloitte 24h')
        self.assertEqual(self.engine.company_calls, [('deloitte', 0, 'owner')])
        self.assertIn('openings posted in the last 7 days', self.api.sent[-1][1])

    def test_owner_companyjobs_defaults_to_7_days_and_keeps_multiword_names(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('owner', '/companyjobs tata consultancy services')
        bot.process('owner', '/companyjobs tata consultancy services 30')
        self.assertEqual(
            self.engine.company_calls,
            [
                ('tata consultancy services', 7, 'owner'),
                ('tata consultancy services', 30, 'owner'),
            ],
        )

    def test_owner_companyjobs_without_company_shows_usage(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('owner', '/companyjobs')
        self.assertEqual(self.engine.company_calls, [])
        self.assertIn('Usage: /companyjobs <company> [24h | 7 | 30]', self.api.sent[-1][1])

    def test_guest_companyjobs_is_denied_like_every_owner_command(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('guest', '/companyjobs deloitte 7')
        self.assertEqual(self.engine.company_calls, [])
        self.assertEqual(
            self.api.sent,
            [('guest', 'JobMaster can help you find verified jobs. Ask naturally in any sentence.')],
        )

    def _mnc_bot(self, tower_post=None):
        return JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
            tower_post=tower_post,
        )

    def test_fresh_board_is_checked_only_and_unfiltered_lifts_it(self):
        rendered: list[tuple[str, dict]] = []

        def board_renderer(board: str, *, days: int | None = None, **kwargs) -> str:
            rendered.append((board, {'days': days, **kwargs}))
            return 'FRESHEST CATCHES'

        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
            board_renderer=board_renderer,
        )
        bot.process('owner', '/fresh')
        bot.process('owner', '/fresh -unfiltered')
        self.assertEqual(rendered[0], ('fresh', {'days': None}))
        self.assertEqual(rendered[1], ('fresh', {'days': None, 'unfiltered': True}))

    def test_owner_addcompany_adds_to_watchlist_and_queues_first_scrape(self):
        posts: list[tuple[str, dict | None]] = []

        def tower_post(path, payload=None):
            posts.append((path, payload))
            return {
                'company': 'Nvidia',
                'created': True,
                'first_scrape_queued': True,
            }

        bot = self._mnc_bot(tower_post)
        bot.process('owner', '/addcompany nvidia')
        self.assertEqual(posts, [('/api/watchlist/companies', {'name': 'nvidia'})])
        reply = self.api.sent[-1][1]
        self.assertIn('✅ Nvidia added to the MNC watchlist', reply)
        self.assertIn('First scrape is queued now', reply)

    def test_owner_addcompany_existing_company_is_honest(self):
        bot = self._mnc_bot(lambda _p, _b=None: {'company': 'Deloitte', 'created': False})
        bot.process('owner', '/addcompany Deloitte')
        self.assertIn('already on the watchlist', self.api.sent[-1][1])

    def test_owner_addcompany_without_name_shows_usage(self):
        posts: list = []
        bot = self._mnc_bot(lambda *a, **k: posts.append(a) or {})
        bot.process('owner', '/addcompany')
        self.assertEqual(posts, [])
        self.assertIn('Usage: /addcompany <company name>', self.api.sent[-1][1])

    def test_guest_addcompany_is_denied(self):
        posts: list = []
        bot = self._mnc_bot(lambda *a, **k: posts.append(a) or {})
        bot.process('guest', '/addcompany nvidia')
        self.assertEqual(posts, [])
        self.assertEqual(
            self.api.sent,
            [('guest', 'JobMaster can help you find verified jobs. Ask naturally in any sentence.')],
        )

    def test_owner_companies_lists_the_full_roster_untruncated(self):
        from datetime import datetime, timedelta, timezone

        recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.engine.companies_roster = {
            'total': 55,
            'companies': [
                {
                    'company': f'Giant {i}',
                    'enabled': i != 55,
                    'jobs_total': 100 - i,
                    'jobs_24h': 3,
                    'last_run_at': recent if i == 1 else None,
                }
                for i in range(1, 56)
            ],
        }
        bot = self._mnc_bot()
        bot.process('owner', '/companies')
        reply = '\n'.join(text for _chat, text in self.api.sent)
        self.assertIn('MNC WATCHLIST · 55 companies · 54 on · 1 paused', reply)
        self.assertIn('1. Giant 1 — 99 jobs (3 in 24h) · scraped 2h ago', reply)
        # Never truncated: the last giant renders too, with honest flags.
        self.assertIn('55. Giant 55 — 45 jobs (3 in 24h) · scraped never · paused', reply)

    def test_owner_companies_empty_watchlist_points_to_addcompany(self):
        self.engine.companies_roster = {'total': 0, 'companies': []}
        bot = self._mnc_bot()
        bot.process('owner', '/companies')
        self.assertIn('/addcompany <name>', self.api.sent[-1][1])

    def test_guest_companies_is_denied(self):
        bot = self._mnc_bot()
        bot.process('guest', '/companies')
        self.assertEqual(
            self.api.sent,
            [('guest', 'JobMaster can help you find verified jobs. Ask naturally in any sentence.')],
        )

    def test_resetdata_stages_with_counts_and_disturbance_warning(self):
        bot = self._mnc_bot()
        bot.process('owner', '/resetdata')
        reply = self.api.sent[-1][1]
        self.assertIn('⚠️ TOWER DATA RESET — staged', reply)
        self.assertIn('4120 jobs · 298 unwatched companies · 890 run records', reply)
        self.assertIn('12 watched companies', reply)
        self.assertIn('1 live search(es) will be cancelled — MNC · Deloitte — Fresher', reply)
        self.assertIn('/resetconfirm within 10 minutes', reply)

    def test_resetconfirm_without_staging_refuses(self):
        posts: list = []
        bot = self._mnc_bot(lambda *a, **k: posts.append(a) or {})
        bot.process('owner', '/resetconfirm')
        self.assertEqual(posts, [])
        self.assertIn('No reset staged', self.api.sent[-1][1])

    def test_staged_reset_confirm_executes_the_wipe(self):
        posts: list[tuple[str, dict | None]] = []

        def tower_post(path, payload=None):
            posts.append((path, payload))
            return {
                'jobs': 4120,
                'companies_unwatched_wiped': 298,
                'runs': 890,
                'cancelled_active': ['MNC · Deloitte — Fresher'],
                'done': True,
            }

        bot = self._mnc_bot(tower_post)
        bot.process('owner', '/resetdata')
        bot.process('owner', '/resetconfirm')
        self.assertEqual(posts, [('/api/tower/reset', {})])
        reply = self.api.sent[-1][1]
        self.assertIn('🧹 Reset done — wiped 4120 jobs', reply)
        self.assertIn('cancelled 1 live search(es)', reply)
        self.assertIn('re-runs automatically', reply)
        # Confirm consumed the staging — a second confirm cannot re-fire.
        bot.process('owner', '/resetconfirm')
        self.assertEqual(len(posts), 1)
        self.assertIn('No reset staged', self.api.sent[-1][1])

    def test_stale_staged_reset_expires_instead_of_firing(self):
        posts: list = []
        bot = self._mnc_bot(lambda *a, **k: posts.append(a) or {})
        bot.process('owner', '/resetdata')
        self.sessions.set_state('pending_reset_at:owner', '1000.0')
        bot.process('owner', '/resetconfirm')
        self.assertEqual(posts, [])
        self.assertIn('expired after 10 minutes', self.api.sent[-1][1])

    def test_resetcancel_discards_the_staging(self):
        posts: list = []
        bot = self._mnc_bot(lambda *a, **k: posts.append(a) or {})
        bot.process('owner', '/resetdata')
        bot.process('owner', '/resetcancel')
        self.assertIn('nothing was wiped', self.api.sent[-1][1])
        bot.process('owner', '/resetconfirm')
        self.assertEqual(posts, [])
        self.assertIn('No reset staged', self.api.sent[-1][1])

    def test_reset_confirm_reports_tower_failure_honestly(self):
        def tower_post(_path, _payload=None):
            raise OSError('tower down')

        bot = self._mnc_bot(tower_post)
        bot.process('owner', '/resetdata')
        bot.process('owner', '/resetconfirm')
        self.assertIn('did NOT execute', self.api.sent[-1][1])

    def test_guest_resetdata_is_denied(self):
        bot = self._mnc_bot()
        bot.process('guest', '/resetdata')
        self.assertEqual(
            self.api.sent,
            [('guest', 'JobMaster can help you find verified jobs. Ask naturally in any sentence.')],
        )

    def test_guest_cannot_run_owner_command(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
            board_renderer=lambda *_args, **_kwargs: self.fail('board must not render'),
        )
        acked = bot._pre_ack('guest', '/health')
        bot.process('guest', '/health', acked=acked)
        self.assertFalse(acked)
        self.assertEqual(
            self.api.sent,
            [('guest', 'JobMaster can help you find verified jobs. Ask naturally in any sentence.')],
        )
        self.assertEqual(self.engine.calls, [])

    def test_guest_cannot_manage_access(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('guest', '/allowguest @intruder')
        self.assertFalse(telegram_guests.is_username_allowed('intruder'))
        self.assertEqual(
            self.api.sent,
            [('guest', 'JobMaster can help you find verified jobs. Ask naturally in any sentence.')],
        )

    def test_owner_can_allow_list_block_and_reallow_username(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('owner', '/allowguest @newperson')
        self.assertTrue(bot._sender_allowed('99', 'newperson'))
        self.assertEqual(self.api.sent[-1], ('owner', 'Allowed @newperson. Their next message will work.'))

        bot.process('owner', '/guests')
        self.assertIn('@newperson', self.api.sent[-1][1])

        bot.process('owner', '/blockguest @newperson')
        self.assertFalse(bot._sender_allowed('99', 'newperson'))
        self.assertIn('newperson', telegram_guests.list_blocked()['usernames'])

        bot.process('owner', '/allowguest @newperson')
        self.assertTrue(bot._sender_allowed('99', 'newperson'))
        self.assertNotIn('newperson', telegram_guests.list_blocked()['usernames'])

    def test_owner_can_read_at_most_forty_guest_conversations(self):
        for index in range(45):
            self.sessions.record_conversation(
                1000 + index,
                '99',
                'cryptoonz',
                f'question {index}',
                f'answer {index}',
                completed_at=1000 + index,
            )
        restarted = TelegramSessionStore(self.sessions.path)
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=restarted,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('owner', '/history @cryptoonz 999')
        reply = self.api.sent[-1][1]
        self.assertIn('CONVERSATION HISTORY · @cryptoonz · latest 40', reply)
        self.assertNotIn('question 4\n', reply)
        self.assertIn('question 5', reply)
        self.assertIn('question 44', reply)
        self.assertLessEqual(_utf16_units(reply), 3700)
        self.assertEqual(
            len(self.sessions.conversation_history('@cryptoonz', limit=40)),
            40,
        )
        self.assertNotIn('Thinking…', [text for _chat, text in self.api.sent])

    def test_recycled_username_history_fails_closed(self):
        self.sessions.record_conversation(
            801,
            '111',
            'cryptoonz',
            'first person secret',
            'first answer',
        )
        self.sessions.record_conversation(
            802,
            '222',
            'cryptoonz',
            'second person secret',
            'second answer',
        )
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('owner', '/history @cryptoonz 40')
        reply = self.api.sent[-1][1]
        self.assertIn('more than one Telegram account', reply)
        self.assertNotIn('first person secret', reply)
        self.assertNotIn('second person secret', reply)

    def test_guest_cannot_read_conversation_history(self):
        self.sessions.record_conversation(
            900,
            '99',
            'cryptoonz',
            'private question',
            'private answer',
        )
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('guest', '/history @cryptoonz 40')
        self.assertNotIn('private question', self.api.sent[-1][1])
        self.assertEqual(
            self.api.sent[-1][1],
            'JobMaster can help you find verified jobs. Ask naturally in any sentence.',
        )

    def test_history_command_explains_pre_feature_gap(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('owner', '/history @cryptoonz 40')
        self.assertEqual(
            self.api.sent[-1][1],
            'No stored conversations for @cryptoonz. '
            'History starts after this feature is deployed.',
        )

    def test_owner_can_timebox_and_block_numeric_guest(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('owner', '/allowguest 12345 30 Investor')
        self.assertTrue(bot._sender_allowed('12345'))
        self.assertIn('Allowed 12345 for 30m', self.api.sent[-1][1])

        bot.process('owner', '/blockguest 12345')
        self.assertFalse(bot._sender_allowed('12345'))
        self.assertIn('12345', telegram_guests.list_blocked()['user_ids'])

    def test_owner_cannot_block_self_or_store_invalid_username(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'12345'},
        )
        bot.process('12345', '/blockguest 12345')
        self.assertEqual(self.api.sent[-1], ('12345', 'Ashok’s owner access cannot be blocked.'))
        self.assertTrue(bot._sender_allowed('12345'))

        bot.process('12345', '/allowguest @bad!')
        self.assertEqual(
            self.api.sent[-1],
            (
                '12345',
                'Use a valid Telegram @username or positive numeric Telegram ID.',
            ),
        )
        self.assertFalse(telegram_guests.is_username_allowed('bad!'))

        for invalid_id in ('0', '-1', '@12345', str(2**52)):
            bot.process('12345', f'/allowguest {invalid_id}')
            self.assertEqual(
                self.api.sent[-1],
                (
                    '12345',
                    'Use a valid Telegram @username or positive numeric Telegram ID.',
                ),
            )

    def test_invalid_guest_expiry_is_rejected_without_grant(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        for invalid_minutes in ('name', '0', '-1', 'inf', '20161'):
            bot.process('owner', f'/allowguest 12345 {invalid_minutes}')
            self.assertIn('Minutes must be a number from 1 to 20160', self.api.sent[-1][1])
            # Open gate (2026-08-06): a rejected /allowguest just means no
            # *temporary* grant was recorded — 12345 is still allowed in,
            # same as any other never-granted stranger.
            self.assertTrue(bot._sender_allowed('12345'))

    def test_queued_guest_is_dropped_after_owner_blocks_username(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('owner', '/allowguest @newperson')
        self.assertTrue(
            self.sessions.queue_update(
                501,
                '99',
                'AI jobs Bangalore',
                username='newperson',
            )
        )
        bot.process('owner', '/blockguest @newperson')
        self.assertTrue(
            bot._process_queued(
                501,
                '99',
                'newperson',
                'AI jobs Bangalore',
            )
        )
        self.assertEqual(self.engine.calls, [])
        self.assertEqual(self.sessions.pending_updates(), [])

    def test_prepared_reply_is_not_sent_after_guest_is_blocked(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('owner', '/allowguest @newperson')
        self.assertTrue(
            self.sessions.queue_update(
                502,
                '99',
                'AI jobs Bangalore',
                username='newperson',
            )
        )
        self.sessions.save_update_reply(502, 'prepared private result')
        bot.process('owner', '/blockguest @newperson')
        sent_before_retry = list(self.api.sent)
        self.assertTrue(
            bot._process_queued(
                502,
                '99',
                'newperson',
                'AI jobs Bangalore',
            )
        )
        self.assertEqual(self.api.sent, sent_before_retry)
        self.assertEqual(self.sessions.pending_updates(), [])

    def test_concurrent_access_mutations_do_not_lose_grants(self):
        handles = [f'user{i:03d}' for i in range(20)]
        with ThreadPoolExecutor(max_workers=8) as workers:
            list(workers.map(telegram_guests.add_username, handles))
        allowed = {item['username'] for item in telegram_guests.list_usernames()}
        self.assertTrue(set(handles).issubset(allowed))

    def test_corrupt_access_store_fails_closed_instead_of_restoring_defaults(self):
        telegram_guests.GUESTS_FILE.write_text('{broken', encoding='utf-8')
        with self.assertRaises(telegram_guests.GuestStoreError):
            telegram_guests.is_allowed('99', 'supriyamk')

        telegram_guests.GUESTS_FILE.write_text(
            json.dumps({
                'guests': {},
                'usernames': {},
                'blocked_ids': {},
                'blocked_usernames': [],
            }),
            encoding='utf-8',
        )
        with self.assertRaises(telegram_guests.GuestStoreError):
            telegram_guests.is_allowed('99', 'supriyamk')

    def test_checkaccess_reports_allowed_for_a_default_username(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('owner', '/checkaccess @supriyamk')
        reply = self.api.sent[-1][1]
        self.assertIn('ALLOWED', reply)
        self.assertIn('supriyamk', reply.lower())

    def test_checkaccess_reports_blocked_with_a_reason_after_blockguest(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('owner', '/blockguest @supriyamk')
        bot.process('owner', '/checkaccess @supriyamk')
        reply = self.api.sent[-1][1]
        self.assertIn('BLOCKED', reply)
        self.assertIn('blocked', reply.lower())

    def test_checkaccess_notes_a_username_bound_to_a_different_telegram_id_but_still_allows(self):
        # Open gate (2026-08-06): a stale/mismatched username↔id binding is
        # informational only now — it never denies access.
        telegram_guests.add_username('newperson')
        telegram_guests.observe_identity('111', 'newperson')
        self.assertTrue(telegram_guests.is_allowed('111', 'newperson'))
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('owner', '/checkaccess @newperson 222')
        reply = self.api.sent[-1][1]
        self.assertIn('ALLOWED', reply)
        self.assertIn('111', reply)

    def test_checkaccess_allows_a_never_before_seen_stranger(self):
        # Open gate (2026-08-06): nobody needs a grant anymore — only an
        # explicit /blockguest denies access.
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('owner', '/checkaccess 555')
        reply = self.api.sent[-1][1]
        self.assertIn('ALLOWED', reply)

    def test_checkaccess_is_denied_to_a_non_owner_like_every_management_command(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        bot.process('guest', '/checkaccess @supriyamk')
        reply = self.api.sent[-1][1]
        self.assertEqual(
            reply,
            'JobMaster can help you find verified jobs. Ask naturally in any sentence.',
        )

    def test_block_override_can_disable_default_username(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        self.assertTrue(bot._sender_allowed('99', 'supriyamk'))
        bot.process('owner', '/blockguest @supriyamk')
        self.assertFalse(bot._sender_allowed('99', 'supriyamk'))
        bot.process('owner', '/allowguest @supriyamk')
        self.assertTrue(bot._sender_allowed('99', 'supriyamk'))

    def test_username_block_also_blocks_observed_numeric_identity(self):
        telegram_guests.add_username('newperson')
        telegram_guests.observe_identity('99', 'newperson')
        telegram_guests.block_username('newperson', blocked_by='owner')
        self.assertFalse(telegram_guests.is_allowed('99', 'changedname'))
        self.assertIn('99', telegram_guests.list_blocked()['user_ids'])

    def test_username_binding_no_longer_restricts_other_ids_under_open_gate(self):
        # Pre-open-gate, a granted @username only "worked" for whichever
        # numeric id it first bound to. That anti-hijack protection existed
        # only to guard the allow-list gate — now that the gate is open by
        # default (2026-08-06), it's moot: any id is allowed regardless.
        telegram_guests.add_username('newperson')
        self.assertTrue(telegram_guests.is_allowed('111', 'newperson'))
        self.assertTrue(telegram_guests.is_allowed('222', 'newperson'))

    def test_a_stranger_with_no_identity_record_at_all_is_still_allowed(self):
        telegram_guests.GUESTS_FILE.write_text(
            json.dumps({
                'guests': {},
                'usernames': {'newperson': {'added_at': 1, 'added_by': 'owner'}},
                'blocked_ids': {},
                'blocked_usernames': {},
                'identities': {
                    '111': {'username': 'newperson', 'seen_at': 1},
                    '222': {'username': 'newperson', 'seen_at': 2},
                },
            }),
            encoding='utf-8',
        )
        self.assertTrue(telegram_guests.is_allowed('111', 'newperson'))
        self.assertTrue(telegram_guests.is_allowed('222', 'newperson'))
        self.assertTrue(telegram_guests.is_allowed('333', 'someone-never-seen'))

    def test_blocking_previous_username_blocks_same_person_after_rename(self):
        telegram_guests.add_guest('99', minutes=60)
        telegram_guests.observe_identity('99', 'oldname')
        telegram_guests.observe_identity('99', 'newname')
        telegram_guests.block_username('oldname', blocked_by='owner')
        self.assertFalse(telegram_guests.is_allowed('99', 'newname'))

    def test_all_observed_aliases_remain_blockable(self):
        telegram_guests.add_guest('99', minutes=60)
        aliases = [f'alias{i:03d}' for i in range(30)]
        for handle in aliases:
            telegram_guests.observe_identity('99', handle)
        telegram_guests.block_username(aliases[0], blocked_by='owner')
        self.assertFalse(telegram_guests.is_allowed('99', aliases[-1]))

    def test_reallowing_a_username_does_not_lift_an_ids_own_block(self):
        # Open gate (2026-08-06): re-running /allowuser is now a no-op for
        # access itself (everyone's already in), but it also must not have
        # a side effect of silently un-blocking a numeric id that
        # block_username had already cascaded to — only /allowguest for
        # that specific id (or the id never having been linked) can do that.
        telegram_guests.add_username('newperson')
        telegram_guests.observe_identity('111', 'newperson')
        telegram_guests.block_username('newperson', blocked_by='owner')
        self.assertFalse(telegram_guests.is_allowed('111', 'newperson'))
        telegram_guests.add_username('newperson', added_by='owner')
        self.assertFalse(telegram_guests.is_allowed('111', 'anything'))
        self.assertTrue(telegram_guests.is_allowed('222', 'newperson'))

    def test_command_menu_is_scoped_only_to_owner_chat(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'1221647274'},
        )
        self.assertTrue(bot._configure_command_menu())
        self.assertEqual(self.api.calls[0][0], 'deleteMyCommands')
        self.assertEqual(json.loads(self.api.calls[0][1]['scope']), {'type': 'default'})
        self.assertEqual(self.api.calls[1][0], 'deleteMyCommands')
        self.assertEqual(
            json.loads(self.api.calls[1][1]['scope']),
            {'type': 'all_private_chats'},
        )
        self.assertEqual(self.api.calls[2][0], 'setMyCommands')
        scope = json.loads(self.api.calls[2][1]['scope'])
        self.assertEqual(scope, {'type': 'chat', 'chat_id': 1221647274})
        commands = json.loads(self.api.calls[2][1]['commands'])
        self.assertIn({'command': 'health', 'description': 'Tower health'}, commands)
        self.assertIn({'command': 'allowguest', 'description': 'Un-block / VIP a person'}, commands)
        self.assertIn(
            {'command': 'blockguest', 'description': 'Block a person (public by default)'},
            commands,
        )
        self.assertIn({'command': 'guests', 'description': 'Access dashboard'}, commands)
        self.assertIn(
            {'command': 'history', 'description': 'Guest conversation history'},
            commands,
        )
        self.assertEqual(len(self.api.calls), 3)

    def test_command_menu_removes_previous_owner_chat_scope(self):
        self.sessions.set_state('telegram_command_owner_ids', '111,222')
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'222'},
        )
        self.assertTrue(bot._configure_command_menu())
        deleted_scopes = [
            json.loads(data['scope'])
            for method, data in self.api.calls
            if method == 'deleteMyCommands'
        ]
        self.assertIn({'type': 'chat', 'chat_id': 111}, deleted_scopes)
        self.assertEqual(
            self.sessions.get_state('telegram_command_owner_ids'),
            '222',
        )

    def test_smoke_sends_only_ten_row_grounded_contract(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=SmokeEngine(valid=True),
            sessions=self.sessions,
            health_enabled=False,
        )
        bot.smoke('42', 'Fresh jobs in Bangalore in AI space for fresher')
        self.assertEqual(self.api.sent[0], ('42', 'Thinking…'))
        self.assertEqual(
            self.api.sent[1][1].count('https://www.linkedin.com/jobs/view/'),
            10,
        )

    def test_smoke_rejects_fallback_before_sending_result(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=SmokeEngine(valid=False),
            sessions=self.sessions,
            health_enabled=False,
        )
        with self.assertRaises(RuntimeError):
            bot.smoke('42', 'Fresh jobs in Bangalore in AI space for fresher')
        self.assertEqual(self.api.sent, [])

    def test_telegram_failure_is_contained_by_worker_boundary(self):
        bot = JobMasterTelegramBot(
            FailingTelegramAPI(),
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
        )
        with self.assertLogs('jobmaster-telegram', level='ERROR'):
            bot._safe_process('42', 'AI jobs Bangalore')
        self.assertEqual(self.engine.calls, [])

    def test_accepted_update_survives_restart_until_completed(self):
        self.assertTrue(self.sessions.queue_update(101, '42', 'AI jobs Bangalore'))
        restarted = TelegramSessionStore(self.sessions.path)
        self.assertEqual(
            restarted.pending_updates(),
            [(101, '42', '', 'AI jobs Bangalore')],
        )
        restarted.complete_update(101)
        self.assertEqual(restarted.pending_updates(), [])

    def test_accepted_update_persists_sender_username(self):
        self.assertTrue(
            self.sessions.queue_update(
                102,
                '42',
                'AI jobs Bangalore',
                username='newperson',
            )
        )
        restarted = TelegramSessionStore(self.sessions.path)
        self.assertEqual(
            restarted.pending_updates(),
            [(102, '42', 'newperson', 'AI jobs Bangalore')],
        )

    def test_existing_history_is_pruned_to_forty_on_store_startup(self):
        with self.sessions._connect() as conn:
            for index in range(100):
                conn.execute(
                    """
                    INSERT INTO conversation_history(
                        update_id, chat_id, username, user_text, bot_reply, completed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        5000 + index,
                        '99',
                        'cryptoonz',
                        f'question {index}',
                        f'answer {index}',
                        float(index),
                    ),
                )
        restarted = TelegramSessionStore(self.sessions.path)
        history = restarted.conversation_history('99', limit=40)
        self.assertEqual(len(history), 40)
        self.assertEqual(history[0]['user_text'], 'question 60')

    def test_successful_delivery_records_conversation_pair(self):
        telegram_guests.add_username('newperson')
        self.assertTrue(
            self.sessions.queue_update(
                103,
                '99',
                'AI jobs Bangalore',
                username='newperson',
            )
        )
        self.assertTrue(
            self.bot._process_queued(
                103,
                '99',
                'newperson',
                'AI jobs Bangalore',
            )
        )
        history = self.sessions.conversation_history('@newperson', limit=40)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['user_text'], 'AI jobs Bangalore')
        self.assertTrue(history[0]['bot_reply'].startswith('1. AI Engineer'))

    def test_owner_commands_are_not_stored_as_guest_history(self):
        self.assertTrue(
            self.sessions.queue_update(
                104,
                '42',
                '/guests',
                username='ashok',
            )
        )
        self.assertTrue(
            self.bot._process_queued(
                104,
                '42',
                'ashok',
                '/guests',
            )
        )
        self.assertEqual(self.sessions.conversation_history('42', limit=40), [])

    def test_history_failure_does_not_strand_delivered_chat(self):
        telegram_guests.add_username('newperson')
        self.assertTrue(
            self.sessions.queue_update(
                105,
                '99',
                'AI jobs Bangalore',
                username='newperson',
            )
        )
        with patch.object(
            self.sessions,
            'finalize_guest_conversation',
            side_effect=OSError('disk full'),
        ):
            with self.assertLogs('jobmaster-telegram', level='ERROR'):
                self.assertTrue(
                    self.bot._process_queued(
                        105,
                        '99',
                        'newperson',
                        'AI jobs Bangalore',
                    )
                )
        self.assertEqual(self.sessions.pending_updates(), [])

    def test_telegram_chunks_respect_utf16_limit(self):
        chunks = _telegram_chunks('💥' * 4000)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(_utf16_units(chunk) <= 3800 for chunk in chunks))
        self.assertEqual(''.join(chunks), '💥' * 4000)

    def test_same_chat_updates_execute_in_telegram_order(self):
        for update_id, text in ((1, '/new'), (2, '/reset'), (3, '/clear')):
            self.sessions.queue_update(update_id, '42', text)
        with ThreadPoolExecutor(max_workers=4) as workers:
            for update_id, chat_id, username, text in self.sessions.pending_updates():
                self.bot._enqueue_update(
                    workers,
                    update_id,
                    chat_id,
                    username,
                    text,
                )
        self.assertEqual(
            [text for text, chat_id in self.engine.calls if chat_id == '42'],
            ['/new', '/reset', '/clear'],
        )

    def test_failed_reply_retries_without_rerunning_or_reordering(self):
        api = FlakyTelegramAPI()
        bot = JobMasterTelegramBot(
            api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'42'},
        )
        for update_id, text in ((1, 'AI jobs Bangalore'), (2, '/new')):
            self.sessions.queue_update(update_id, '42', text)
        with self.assertLogs('jobmaster-telegram', level='ERROR'):
            with ThreadPoolExecutor(max_workers=2) as workers:
                for update_id, chat_id, username, text in self.sessions.pending_updates():
                    bot._enqueue_update(
                        workers,
                        update_id,
                        chat_id,
                        username,
                        text,
                    )
        self.assertEqual(self.engine.calls, [('AI jobs Bangalore', '42'), ('/new', '42')])
        replies = [text for _chat, text in api.sent if text != 'Thinking…']
        self.assertEqual(
            replies,
            [
                '1. AI Engineer — Acme — Fresher\n'
                'https://www.linkedin.com/jobs/view/4448000001/',
                'Search reset. Send a role, city, or job-market question.\n\n'
                'JobMaster here! What kind of role are you looking for?',
            ],
        )


class RoleSwitchSelfTestTests(unittest.TestCase):
    """/actasguest + /actasowner — test the guest experience with no second
    phone by making Ashok's own chat behave like a guest, without ever being
    able to lock him out of it."""

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
        self.api = FakeTelegramAPI()
        self.engine = FakeEngine()
        self.rendered: list[tuple[str, int | None]] = []
        self.bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
            board_renderer=lambda board, *, days=None: self.rendered.append((board, days))
            or 'TOWER HEALTH · 72°',
        )

    def tearDown(self):
        self.env_patch.stop()
        self.guests_patch.stop()
        self.tmp.cleanup()

    def test_actasguest_denies_owner_commands_in_that_chat(self):
        self.bot.process('owner', '/actasguest')
        self.assertIn('Testing mode ON', self.api.sent[-1][1])
        self.bot.process('owner', '/health')
        self.assertEqual(
            self.api.sent[-1][1],
            'JobMaster can help you find verified jobs. Ask naturally in any sentence.',
        )
        self.assertEqual(self.rendered, [])

    def test_actasguest_hides_and_actasowner_restores_the_command_menu(self):
        self.bot.process('owner', '/actasguest')
        hide_calls = [call for call in self.api.calls if call[0] == 'deleteMyCommands']
        self.assertTrue(hide_calls)
        self.bot.process('owner', '/actasowner')
        restore_calls = [call for call in self.api.calls if call[0] == 'setMyCommands']
        self.assertTrue(restore_calls)
        self.assertIn('Testing mode OFF', self.api.sent[-1][1])

    def test_actasowner_restores_owner_commands(self):
        self.bot.process('owner', '/actasguest')
        self.bot.process('owner', '/actasowner')
        self.bot.process('owner', '/health')
        self.assertEqual(self.api.sent[-1][1], 'TOWER HEALTH · 72°')
        self.assertEqual(self.rendered, [('health', None)])

    def test_owner_is_never_silently_dropped_while_testing_as_a_guest(self):
        self.bot.process('owner', '/actasguest')
        self.bot._last_request.clear()
        self.bot.process('owner', 'AI jobs Bangalore')
        self.assertTrue(self.api.sent[-1][1].startswith('1. AI Engineer'))

    def test_search_conversations_are_recorded_like_a_guests_while_testing(self):
        self.bot.process('owner', '/actasguest')
        self.assertTrue(
            self.sessions.queue_update(
                501, 'owner', 'AI jobs Bangalore', username='ashok',
            )
        )
        self.assertTrue(
            self.bot._process_queued(501, 'owner', 'ashok', 'AI jobs Bangalore')
        )
        history = self.sessions.conversation_history('ashok', limit=10)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['user_text'], 'AI jobs Bangalore')

    def test_a_real_guest_cannot_flip_anyones_role_switch(self):
        self.bot.process('guest', '/actasguest')
        self.assertEqual(
            self.api.sent[-1][1],
            'JobMaster can help you find verified jobs. Ask naturally in any sentence.',
        )
        self.assertFalse(self.bot._is_simulating_guest('guest'))

    def test_repeat_toggles_are_idempotent_with_a_clear_reply(self):
        self.bot.process('owner', '/actasguest')
        self.bot.process('owner', '/actasguest')
        self.assertIn('Already testing as a guest', self.api.sent[-1][1])
        self.bot.process('owner', '/actasowner')
        self.bot.process('owner', '/actasowner')
        self.assertIn('Already in owner mode', self.api.sent[-1][1])

    def test_toggle_state_persists_across_a_restart(self):
        self.bot.process('owner', '/actasguest')
        restarted = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=TelegramSessionStore(self.sessions.path),
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        restarted.process('owner', '/health')
        self.assertEqual(
            self.api.sent[-1][1],
            'JobMaster can help you find verified jobs. Ask naturally in any sentence.',
        )


class VoiceLayerWiringTests(unittest.TestCase):
    """1A (Ashok 2026-08-05): the bot must run every grounded job-search/
    insight reply and the /start · /help message through the voice layer,
    but never an owner VIGIL board/management command — those must stay
    exactly deterministic. See app/telegram_voice.py for the fact-lock
    validator that makes the warmth pass itself safe; this suite only
    covers the *wiring* (who gets voiced, who doesn't, and that a fresh
    reply is voiced exactly once — not on a durable retry)."""

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
        self.api = FakeTelegramAPI()
        self.engine = FakeEngine()
        self.voice = FakeVoice()
        self.bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
            voice=self.voice,
        )

    def tearDown(self):
        self.guests_patch.stop()
        self.env_patch.stop()
        self.tmp.cleanup()

    def test_job_search_reply_is_voiced(self):
        self.bot.process('guest', 'AI jobs Bangalore')
        expected = (
            '1. AI Engineer — Acme — Fresher\n'
            'https://www.linkedin.com/jobs/view/4448000001/'
        )
        self.assertEqual(self.api.sent[-1][1], f'{self.voice.prefix}{expected}')
        self.assertEqual(len(self.voice.calls), 1)

    def test_help_reply_is_voiced(self):
        self.bot.process('guest', '/help')
        self.assertTrue(self.api.sent[-1][1].startswith(self.voice.prefix))

    def test_start_reply_is_the_deterministic_button_flow_not_voiced(self):
        # /start now launches the button wizard — deterministic, no LLM
        # warmth pass (kept snappy, and the fact-lock validator is one
        # fewer moving part to reason about on a screen with no facts yet).
        self.bot.process('guest', '/start')
        self.assertFalse(self.api.sent[-1][1].startswith(self.voice.prefix))
        self.assertEqual(len(self.voice.calls), 0)

    def test_owner_board_command_is_never_voiced(self):
        bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
            board_renderer=lambda *_a, **_k: 'TOWER HEALTH · 72°',
            voice=self.voice,
        )
        bot.process('owner', '/health')
        self.assertEqual(self.api.sent[-1], ('owner', 'TOWER HEALTH · 72°'))
        self.assertEqual(self.voice.calls, [])

    def test_owner_management_command_is_never_voiced(self):
        self.bot.process('owner', '/allowguest @newperson')
        self.assertEqual(
            self.api.sent[-1],
            ('owner', 'Allowed @newperson. Their next message will work.'),
        )
        self.assertEqual(self.voice.calls, [])

    def test_engine_failure_fallback_is_never_voiced(self):
        class BrokenEngine:
            def handle(self, *_args, **_kwargs):
                raise RuntimeError('boom')

        bot = JobMasterTelegramBot(
            self.api,
            engine=BrokenEngine(),
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
            voice=self.voice,
        )
        bot.process('guest', 'AI jobs Bangalore')
        self.assertEqual(
            self.api.sent[-1][1],
            'JobMaster could not reach live Watch Tower data. Try again shortly.',
        )
        self.assertEqual(self.voice.calls, [])

    def test_durable_retry_reuses_the_already_voiced_reply_without_recomputing(self):
        telegram_guests.add_guest('guest', minutes=60, added_by='test')
        self.assertTrue(
            self.sessions.queue_update(1, 'guest', 'AI jobs Bangalore', username=''),
        )
        self.assertTrue(self.bot._process_queued(1, 'guest', '', 'AI jobs Bangalore'))
        self.assertEqual(len(self.voice.calls), 1)
        voiced_once = self.api.sent[-1][1]

        # Requeue the same update as a durability replay (e.g. after a crash
        # before the inbox row was cleared) — the prepared reply must be
        # resent as-is, never re-voiced a second time.
        self.sessions.queue_update(1, 'guest', 'AI jobs Bangalore', username='')
        self.sessions.save_update_reply(1, voiced_once)
        self.assertTrue(self.bot._process_queued(1, 'guest', '', 'AI jobs Bangalore'))
        self.assertEqual(len(self.voice.calls), 1)
        self.assertEqual(self.api.sent[-1][1], voiced_once)


class MyAlertsCommandTests(unittest.TestCase):
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
        self.api = FakeTelegramAPI()
        self.bot = JobMasterTelegramBot(
            self.api,
            engine=FakeEngine(),
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )

    def tearDown(self):
        self.guests_patch.stop()
        self.env_patch.stop()
        self.tmp.cleanup()

    def test_myalerts_with_no_subscriptions_gives_a_helpful_empty_state(self):
        self.bot.process('guest', '/myalerts')
        self.assertIn('no active alerts', self.api.sent[-1][1])

    def test_myalerts_lists_active_alerts_with_a_stop_button(self):
        self.sessions.create_job_alert(
            'guest', role_family='ai_ml', role_keywords=[], role_label='AI/ML', city='chennai',
        )
        self.bot.process('guest', '/myalerts')
        text, keyboard = self.api.keyboards_sent[-1][1], self.api.keyboards_sent[-1][2]
        self.assertIn('AI/ML', text)
        labels = [label for row in keyboard for label, _data in row]
        self.assertIn('🔕 Stop #1', labels)

    def test_myalerts_never_triggers_thinking_ack(self):
        acked = self.bot._pre_ack('guest', '/myalerts')
        self.assertFalse(acked)


class AlertAndPushCallbackTests(unittest.TestCase):
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
        self.api = FakeTelegramAPI()
        self.bot = JobMasterTelegramBot(
            self.api,
            engine=FakeEngine(),
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )

    def tearDown(self):
        self.guests_patch.stop()
        self.env_patch.stop()
        self.tmp.cleanup()

    def test_alert_off_deactivates_the_owning_chats_alert(self):
        alert = self.sessions.create_job_alert(
            'guest', role_family='ai_ml', role_keywords=[], role_label='AI/ML', city='',
        )
        self.bot.process('guest', f'{BTN_PREFIX}alert:off:{alert["id"]}')
        self.assertIn('Stopped the alert', self.api.sent[-1][1])
        self.assertEqual(self.sessions.list_job_alerts('guest'), [])

    def test_alert_off_on_an_auto_alert_opts_the_guest_out_of_auto_alerts(self):
        """🔕 on an AUTO alert must be a real opt-out (Ashok, 2026-08-09):
        no future search silently re-enrols someone who just said stop."""
        alert = self.sessions.create_job_alert(
            'guest', role_family='ai_ml', role_keywords=[], role_label='AI/ML',
            city='', source='auto',
        )
        self.bot.process('guest', f'{BTN_PREFIX}alert:off:{alert["id"]}')
        self.assertIn("won't set alerts from your searches automatically", self.api.sent[-1][1])
        self.assertEqual(self.sessions.list_job_alerts('guest'), [])
        self.assertTrue(telegram_alerts.is_auto_opted_out(self.sessions, 'guest'))

    def test_alert_off_on_a_manual_alert_does_not_opt_out_of_auto_alerts(self):
        alert = self.sessions.create_job_alert(
            'guest', role_family='ai_ml', role_keywords=[], role_label='AI/ML', city='',
        )
        self.bot.process('guest', f'{BTN_PREFIX}alert:off:{alert["id"]}')
        self.assertIn('Stopped the alert', self.api.sent[-1][1])
        self.assertFalse(telegram_alerts.is_auto_opted_out(self.sessions, 'guest'))

    def test_alert_off_from_a_different_chat_is_refused(self):
        alert = self.sessions.create_job_alert(
            'owner-of-alert', role_family='ai_ml', role_keywords=[], role_label='AI/ML', city='',
        )
        self.bot.process('someone-else', f'{BTN_PREFIX}alert:off:{alert["id"]}')
        self.assertIn('no longer active', self.api.sent[-1][1])
        self.assertEqual(len(self.sessions.list_job_alerts('owner-of-alert')), 1)

    def test_alert_like_increments_the_like_counter(self):
        alert = self.sessions.create_job_alert(
            'guest', role_family='ai_ml', role_keywords=[], role_label='AI/ML', city='',
        )
        self.bot.process('guest', f'{BTN_PREFIX}alert:like:{alert["id"]}')
        self.assertIn('Thanks for the feedback', self.api.sent[-1][1])
        self.assertEqual(self.sessions.get_job_alert(alert['id'])['likes'], 1)

    def test_push_stop_removes_the_chat_from_the_broadcast_list(self):
        self.sessions.record_broadcast_start('guest')
        self.bot.process('guest', f'{BTN_PREFIX}push:stop')
        self.assertIn("won't receive further updates", self.api.sent[-1][1])
        self.assertEqual(self.sessions.list_active_broadcast_subscribers(), [])

    def test_push_like_increments_the_push_like_counter(self):
        push_id = self.sessions.create_broadcast_push(text='hi')
        self.bot.process('guest', f'{BTN_PREFIX}push:like:{push_id}')
        self.assertIn('Thanks for the feedback', self.api.sent[-1][1])
        self.assertEqual(self.sessions.latest_broadcast_push()['like_count'], 1)

    def test_any_inbound_message_reactivates_a_pruned_subscriber_via_process(self):
        """process() itself doesn't run the poll loop's activity hook (that
        lives in run()'s per-update handling) — covered separately at the
        poll-loop layer in PushBroadcastCommandTests; this just proves the
        underlying primitive process() would need is wired correctly."""
        self.sessions.record_broadcast_start('guest')
        self.sessions.stop_broadcast('guest')
        telegram_broadcast.record_activity(self.sessions, 'guest')
        self.assertEqual(self.sessions.list_active_broadcast_subscribers(), ['guest'])


class PushBroadcastCommandTests(unittest.TestCase):
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
        self.api = FakeTelegramAPI()
        self.bot = JobMasterTelegramBot(
            self.api,
            engine=FakeEngine(),
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'owner'},
        )
        self.sessions.record_broadcast_start('guest-1')
        self.sessions.record_broadcast_start('guest-2')

    def tearDown(self):
        self.guests_patch.stop()
        self.env_patch.stop()
        self.tmp.cleanup()

    def test_push_stages_a_pending_broadcast_and_reports_recipient_count(self):
        self.bot.process('owner', '/push New AI/ML jobs just dropped!')
        reply = self.api.sent[-1][1]
        self.assertIn('READY TO SEND', reply)
        self.assertIn('2 subscriber', reply)
        self.assertIn('New AI/ML jobs just dropped!', reply)
        # Nothing sent to guests yet — only confirmation can trigger delivery.
        self.assertEqual([c for c in self.api.sent if c[0] in ('guest-1', 'guest-2')], [])

    def test_guest_cannot_stage_a_push(self):
        self.bot.process('guest-1', '/push hello everyone')
        self.assertEqual(
            self.api.sent[-1][1],
            'JobMaster can help you find verified jobs. Ask naturally in any sentence.',
        )
        self.assertEqual(self.sessions.get_state('pending_push_text:guest-1', ''), '')

    def test_pushconfirm_without_a_staged_push_is_refused(self):
        self.bot.process('owner', '/pushconfirm')
        self.assertIn('No pending push', self.api.sent[-1][1])

    def test_pushconfirm_sends_to_every_active_subscriber(self):
        self.bot.process('owner', '/push New AI/ML jobs just dropped!')
        self.bot.process('owner', '/pushconfirm')
        self.assertIn('Sent to 2/2 subscriber', self.api.sent[-1][1])
        delivered = {chat for chat, _text, _kb in self.api.keyboards_sent if chat in ('guest-1', 'guest-2')}
        self.assertEqual(delivered, {'guest-1', 'guest-2'})
        _chat, text, keyboard = next(
            row for row in self.api.keyboards_sent if row[0] == 'guest-1'
        )
        self.assertIn('New AI/ML jobs just dropped!', text)
        labels = [label for row in keyboard for label, _data in row]
        self.assertIn('👍 Like', labels)
        self.assertIn('🔕 Stop notifications', labels)

    def test_pushconfirm_clears_state_so_a_second_confirm_has_nothing_to_send(self):
        self.bot.process('owner', '/push hello')
        self.bot.process('owner', '/pushconfirm')
        self.bot.process('owner', '/pushconfirm')
        self.assertIn('No pending push', self.api.sent[-1][1])

    def test_pushcancel_discards_the_staged_push(self):
        self.bot.process('owner', '/push hello')
        self.bot.process('owner', '/pushcancel')
        self.bot.process('owner', '/pushconfirm')
        self.assertIn('No pending push', self.api.sent[-1][1])

    def test_pushstats_with_no_prior_push_reports_subscriber_count_only(self):
        self.bot.process('owner', '/pushstats')
        self.assertIn('No pushes sent yet', self.api.sent[-1][1])
        self.assertIn('2', self.api.sent[-1][1])

    def test_pushstats_after_a_push_reports_reach_and_likes(self):
        self.bot.process('owner', '/push hello')
        self.bot.process('owner', '/pushconfirm')
        self.bot.process('owner', '/pushstats')
        reply = self.api.sent[-1][1]
        self.assertIn('LAST PUSH', reply)
        self.assertIn('Reached 2', reply)
        self.assertIn('👍 0 likes', reply)

    def test_a_subscriber_dropped_after_three_unanswered_pushes_stops_receiving_them(self):
        for _ in range(3):
            self.bot.process('owner', '/push hello')
            self.bot.process('owner', '/pushconfirm')
        self.assertEqual(self.sessions.list_active_broadcast_subscribers(), [])
        self.bot.process('owner', '/push hello again')
        self.assertIn('0 subscriber', self.api.sent[-1][1])

    def test_photo_caption_push_is_staged_with_the_stashed_photo(self):
        """The durable inbox is text-only; a photo's file_id is stashed by
        the poll loop before /push ever runs (see run()) — here we simulate
        that stash directly since process() itself is below the poll loop."""
        self.sessions.set_state('pending_push_photo:owner', 'file-abc')
        self.bot.process('owner', '/push Check this out')
        self.assertIn('text + photo', self.api.sent[-1][1])
        self.bot.process('owner', '/pushconfirm')
        self.assertEqual(len(self.api.photos_sent), 2)
        chat_id, photo_file_id, caption, keyboard = self.api.photos_sent[0]
        self.assertIn(chat_id, ('guest-1', 'guest-2'))
        self.assertEqual(photo_file_id, 'file-abc')
        self.assertIn('Check this out', caption)
        labels = [label for row in keyboard for label, _data in row]
        self.assertIn('👍 Like', labels)


class NormalizeUpdateTests(unittest.TestCase):
    """`_normalize_update` folds message vs callback_query updates into one
    shape the poll loop dispatches uniformly (see run()). Covered in
    isolation because run()'s own polling loop is not exercised by other
    tests — this is the exact regression that shipped once (the method was
    called but never defined)."""

    def test_a_plain_text_message_is_not_a_callback(self):
        update = {
            'update_id': 1,
            'message': {
                'chat': {'id': 42, 'type': 'private'},
                'from': {'username': 'ashok', 'id': 42},
                'text': 'Fresh AI jobs in Bangalore',
            },
        }
        is_callback, chat, sender, text, callback_id, photo_file_id = (
            JobMasterTelegramBot._normalize_update(update)
        )
        self.assertFalse(is_callback)
        self.assertEqual(chat, {'id': 42, 'type': 'private'})
        self.assertEqual(sender['username'], 'ashok')
        self.assertEqual(text, 'Fresh AI jobs in Bangalore')
        self.assertIsNone(callback_id)
        self.assertEqual(photo_file_id, '')

    def test_a_button_tap_is_a_callback_encoded_with_btn_prefix(self):
        update = {
            'update_id': 2,
            'callback_query': {
                'id': 'cbq-1',
                'from': {'username': 'guest1', 'id': 7},
                'message': {'chat': {'id': 7, 'type': 'private'}},
                'data': 'fam:ai_ml',
            },
        }
        is_callback, chat, sender, text, callback_id, photo_file_id = (
            JobMasterTelegramBot._normalize_update(update)
        )
        self.assertTrue(is_callback)
        self.assertEqual(chat, {'id': 7, 'type': 'private'})
        self.assertEqual(sender['username'], 'guest1')
        self.assertEqual(text, f'{BTN_PREFIX}fam:ai_ml')
        self.assertEqual(callback_id, 'cbq-1')
        self.assertEqual(photo_file_id, '')

    def test_a_callback_query_with_no_data_yields_no_text_but_still_a_callback_id(self):
        update = {
            'update_id': 3,
            'callback_query': {
                'id': 'cbq-2',
                'from': {'id': 7},
                'message': {'chat': {'id': 7, 'type': 'private'}},
            },
        }
        is_callback, _chat, _sender, text, callback_id, photo_file_id = (
            JobMasterTelegramBot._normalize_update(update)
        )
        self.assertTrue(is_callback)
        self.assertIsNone(text)
        self.assertEqual(callback_id, 'cbq-2')
        self.assertEqual(photo_file_id, '')

    def test_a_non_private_group_chat_message_still_normalizes_cleanly(self):
        update = {
            'update_id': 4,
            'message': {
                'chat': {'id': -100, 'type': 'group'},
                'from': {'username': 'someone', 'id': 5},
                'text': 'hi',
            },
        }
        is_callback, chat, _sender, text, _callback_id, _photo_file_id = (
            JobMasterTelegramBot._normalize_update(update)
        )
        self.assertFalse(is_callback)
        self.assertEqual(chat['type'], 'group')
        self.assertEqual(text, 'hi')

    def test_a_photo_with_caption_yields_caption_as_text_plus_file_id(self):
        update = {
            'update_id': 5,
            'message': {
                'chat': {'id': 42, 'type': 'private'},
                'from': {'username': 'ashok', 'id': 42},
                'photo': [
                    {'file_id': 'small', 'width': 90},
                    {'file_id': 'large', 'width': 800},
                ],
                'caption': '/push New AI/ML openings just dropped!',
            },
        }
        is_callback, _chat, _sender, text, _callback_id, photo_file_id = (
            JobMasterTelegramBot._normalize_update(update)
        )
        self.assertFalse(is_callback)
        self.assertEqual(text, '/push New AI/ML openings just dropped!')
        self.assertEqual(photo_file_id, 'large')

    def test_a_photo_with_no_caption_yields_no_text_but_still_a_file_id(self):
        update = {
            'update_id': 6,
            'message': {
                'chat': {'id': 42, 'type': 'private'},
                'from': {'username': 'ashok', 'id': 42},
                'photo': [{'file_id': 'only', 'width': 400}],
            },
        }
        is_callback, _chat, _sender, text, _callback_id, photo_file_id = (
            JobMasterTelegramBot._normalize_update(update)
        )
        self.assertFalse(is_callback)
        self.assertIsNone(text)
        self.assertEqual(photo_file_id, 'only')


class TopFreshersCommandTests(unittest.TestCase):
    """/topfreshers — video gems: verified + explicitly-stated fresher/0-exp
    only, with company: / skill: / role: filters (owner-only)."""

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
        self.api = FakeTelegramAPI()
        self.engine = FakeEngine()
        self.bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'42'},
        )

    def tearDown(self):
        self.env_patch.stop()
        self.guests_patch.stop()
        self.tmp.cleanup()

    def _last_jobs_params(self) -> dict:
        calls = [p for path, p in self.engine.api_calls if path == '/api/jobs']
        self.assertTrue(calls, 'expected an /api/jobs call')
        return calls[-1] or {}

    def test_bare_zero_lists_all_verified_explicit_gems(self):
        self.bot.process('42', '/topfreshers 0')
        params = self._last_jobs_params()
        self.assertEqual(params.get('verified'), 1)
        self.assertEqual(params.get('explicit_fresher'), 1)
        self.assertNotIn('company', params)
        self.assertNotIn('skill', params)
        text = self.api.sent[-1][1]
        self.assertIn('TOP FRESHER GEMS', text)
        self.assertIn('Data Analyst (Fresher) — Deloitte — Bengaluru', text)
        self.assertIn('https://www.linkedin.com/jobs/view/4448000301/', text)

    def test_company_filter_reaches_the_api(self):
        self.bot.process('42', '/topfreshers company:Deloitte 0')
        params = self._last_jobs_params()
        self.assertEqual(params.get('company'), 'Deloitte')
        self.assertEqual(params.get('verified'), 1)
        self.assertEqual(params.get('explicit_fresher'), 1)
        self.assertIn('Filters: company: Deloitte', self.api.sent[-1][1])

    def test_multi_word_company_parses_whole(self):
        self.bot.process('42', '/topfreshers company:Tata Consultancy Services 0')
        self.assertEqual(self._last_jobs_params().get('company'), 'Tata Consultancy Services')

    def test_skill_filter_reaches_the_api(self):
        self.bot.process('42', '/topfreshers skill:sql 0')
        params = self._last_jobs_params()
        self.assertEqual(params.get('skill'), 'sql')
        self.assertEqual(params.get('explicit_fresher'), 1)

    def test_role_maps_to_family_when_known_else_title_terms(self):
        self.bot.process('42', '/topfreshers role:data 0')
        self.assertEqual(self._last_jobs_params().get('role_family'), 'data')
        self.bot.process('42', '/topfreshers role:tester 0')
        params = self._last_jobs_params()
        self.assertEqual(params.get('title_terms'), 'tester')
        self.assertNotIn('role_family', params)

    def test_combined_filters(self):
        self.bot.process('42', '/topfreshers company:Deloitte skill:sql 0')
        params = self._last_jobs_params()
        self.assertEqual(params.get('company'), 'Deloitte')
        self.assertEqual(params.get('skill'), 'sql')

    def test_nonzero_level_is_refused_honestly(self):
        self.bot.process('42', '/topfreshers 2')
        text = self.api.sent[-1][1]
        self.assertIn('Only 0 is supported', text)
        self.assertIn('Usage: /topfreshers', text)
        self.assertEqual(
            [p for path, p in self.engine.api_calls if path == '/api/jobs'], [],
        )

    def test_empty_result_mentions_the_verification_queue(self):
        self.engine.jobs_rows = []
        self.bot.process('42', '/topfreshers company:Nvidia 0')
        text = self.api.sent[-1][1]
        self.assertIn('No checked explicit-fresher gems', text)
        self.assertIn('/health', text)

    def test_long_lists_page_ten_with_a_more_button(self):
        self.engine.jobs_rows = [
            {
                'title': f'Fresher Analyst {i}',
                'company': 'Deloitte',
                'city_key': 'bengaluru',
                'location': 'Bengaluru',
                'linkedin_job_id': f'id-{i}',
                'job_url': f'https://www.linkedin.com/jobs/view/{4448001000 + i}/',
            }
            for i in range(35)
        ]
        self.bot.process('42', '/topfreshers 0')
        text = self.api.sent[-1][1]
        self.assertIn('Fresher Analyst 0', text)
        self.assertIn('Fresher Analyst 9', text)
        self.assertNotIn('Fresher Analyst 10', text)
        self.assertIn('Reply more for 10 more gems.', text)
        self.assertTrue(self.api.keyboards_sent, 'expected More gems keyboard')
        # Page 2 via typed "more"
        self.bot.process('42', 'more')
        text2 = self.api.sent[-1][1]
        self.assertIn('Fresher Analyst 10', text2)
        self.assertIn('Fresher Analyst 19', text2)
        self.assertNotIn('Fresher Analyst 9', text2)
        self.assertNotIn('Fresher Analyst 20', text2)

    def test_city_skill_time_filters_reach_the_api(self):
        self.bot.process(
            '42',
            '/topfreshers skill:data_analyst city:chennai/bangalore/remote time:24hrs',
        )
        params = self._last_jobs_params()
        self.assertEqual(params.get('skill'), 'data_analyst')
        self.assertEqual(params.get('city'), 'chennai/bangalore/remote')
        self.assertEqual(params.get('days'), 0)
        self.assertEqual(params.get('verified'), 1)
        self.assertEqual(params.get('explicit_fresher'), 1)
        text = self.api.sent[-1][1]
        self.assertIn('skill: data_analyst', text)
        self.assertIn('city: chennai/bangalore/remote', text)
        self.assertIn('time: 24hrs', text)

    def test_trailing_zero_is_optional(self):
        self.bot.process('42', '/topfreshers city:chennai/bangalore/remote time:24hrs')
        params = self._last_jobs_params()
        self.assertEqual(params.get('city'), 'chennai/bangalore/remote')
        self.assertEqual(params.get('days'), 0)

    def test_salary_shows_on_the_row_only_when_employer_stated_it(self):
        self.bot.process('42', '/topfreshers 0')
        text = self.api.sent[-1][1]
        # Deloitte row carries the AI quote-grounded salary; Oracle row
        # (no stated salary) stays clean — never an invented number.
        self.assertIn('💰 INR 4,50,000 - 6,00,000 per annum', text)
        oracle_line = next(line for line in text.splitlines() if 'Oracle' in line)
        self.assertNotIn('💰', oracle_line)

    def test_guests_never_reach_topfreshers(self):
        self.bot.process('guest-9', '/topfreshers 0')
        self.assertEqual(
            self.api.sent[-1][1],
            'JobMaster can help you find verified jobs. Ask naturally in any sentence.',
        )
        self.assertEqual(self.engine.api_calls, [])


class FunnelCommandTests(unittest.TestCase):
    """/funnel — where jobs die between LinkedIn and the bot (owner-only)."""

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
        self.api = FakeTelegramAPI()
        self.engine = FakeEngine()
        self.bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'42'},
        )

    def tearDown(self):
        self.env_patch.stop()
        self.guests_patch.stop()
        self.tmp.cleanup()

    def test_funnel_shows_every_gate_count(self):
        self.bot.process('42', '/funnel')
        text = self.api.sent[-1][1]
        self.assertIn('JOB FUNNEL · last 24h', text)
        self.assertIn('Caught: 42', text)
        self.assertIn('in Chennai/Bengaluru/Remote: 30', text)
        self.assertIn('GTM role titles: 25', text)
        self.assertIn('detail-verified: 18', text)
        self.assertIn('servable fresher gems: 7', text)
        self.assertIn('Pending verification: 24', text)

    def test_funnel_accepts_a_custom_window(self):
        self.bot.process('42', '/funnel 48')
        params = [p for path, p in self.engine.api_calls if path == '/api/jobs/funnel'][-1]
        self.assertEqual(params.get('hours'), 48)

    def test_bad_window_gets_usage(self):
        self.bot.process('42', '/funnel yesterday')
        self.assertIn('Usage: /funnel', self.api.sent[-1][1])

    def test_guests_never_reach_funnel(self):
        self.bot.process('guest-3', '/funnel')
        self.assertEqual(
            self.api.sent[-1][1],
            'JobMaster can help you find verified jobs. Ask naturally in any sentence.',
        )
        self.assertEqual(self.engine.api_calls, [])

    def test_empty_topfreshers_includes_the_funnel_snapshot(self):
        self.engine.jobs_rows = []
        self.bot.process('42', '/topfreshers 0')
        text = self.api.sent[-1][1]
        self.assertIn('No checked explicit-fresher gems', text)
        self.assertIn('Funnel 24h: 42 caught · 18 verified · 7 servable', text)
        self.assertIn('/funnel', text)


if __name__ == '__main__':
    unittest.main()
