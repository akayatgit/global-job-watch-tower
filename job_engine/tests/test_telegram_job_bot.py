from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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
        self.api = FakeTelegramAPI()
        self.engine = FakeEngine()
        self.bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
        )

    def tearDown(self):
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
        self.assertEqual(len(self.api.calls), 3)

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
        self.assertEqual(restarted.pending_updates(), [(101, '42', 'AI jobs Bangalore')])
        restarted.complete_update(101)
        self.assertEqual(restarted.pending_updates(), [])

    def test_same_chat_updates_execute_in_telegram_order(self):
        for update_id, text in ((1, '/new'), (2, '/reset'), (3, '/clear')):
            self.sessions.queue_update(update_id, '42', text)
        with ThreadPoolExecutor(max_workers=4) as workers:
            for update_id, chat_id, text in self.sessions.pending_updates():
                self.bot._enqueue_update(workers, update_id, chat_id, text)
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
        )
        for update_id, text in ((1, 'AI jobs Bangalore'), (2, '/new')):
            self.sessions.queue_update(update_id, '42', text)
        with self.assertLogs('jobmaster-telegram', level='ERROR'):
            with ThreadPoolExecutor(max_workers=2) as workers:
                for update_id, chat_id, text in self.sessions.pending_updates():
                    bot._enqueue_update(workers, update_id, chat_id, text)
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
