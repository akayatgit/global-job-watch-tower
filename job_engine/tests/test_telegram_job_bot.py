from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app import telegram_guests
from app.telegram_sessions import TelegramSessionStore
from scripts.telegram_job_bot import JobMasterTelegramBot


class FakeTelegramAPI:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.calls: list[tuple[str, dict]] = []

    def send(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))

    def call(self, method: str, data: dict | None = None, timeout: int = 35) -> dict:
        self.calls.append((method, data or {}))
        return {'ok': True}


class FakeEngine:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def handle(self, text: str, chat_id: str) -> str:
        self.calls.append((text, chat_id))
        if text == '/new':
            return 'Search reset. Send a role, city, or job-market question.'
        return '1. AI Engineer — Acme — Fresher\nhttps://www.linkedin.com/jobs/view/4448000001/'


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
        self.assertEqual(
            self.api.sent,
            [('1221647274', 'Search reset. Send a role, city, or job-market question.')],
        )
        text = self.api.sent[0][1]
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
        self.bot.process('42', '/start')
        self.assertEqual(
            self.api.sent[-1][1],
            'JobMaster provides verified jobs and live job-market insights. '
            'Ask naturally in any sentence.',
        )

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
        self.assertNotIn('Thinking…', [text for _chat, text in self.api.sent])

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
            self.assertFalse(bot._sender_allowed('12345'))

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
        self.assertIn({'command': 'allowguest', 'description': 'Allow a person'}, commands)
        self.assertIn({'command': 'blockguest', 'description': 'Block a person'}, commands)
        self.assertIn({'command': 'guests', 'description': 'People with access'}, commands)
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
                'Search reset. Send a role, city, or job-market question.',
            ],
        )


if __name__ == '__main__':
    unittest.main()
