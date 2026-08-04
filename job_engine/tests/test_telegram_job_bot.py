from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.telegram_sessions import TelegramSessionStore
from scripts.telegram_job_bot import JobMasterTelegramBot


class FakeTelegramAPI:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))


class FakeEngine:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def handle(self, text: str, chat_id: str) -> str:
        self.calls.append((text, chat_id))
        if text == '/new':
            return 'Search reset. Send a role, city, or job-market question.'
        return '1. AI Engineer — Acme — Fresher\nhttps://www.linkedin.com/jobs/view/4448000001/'


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
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_thinking_is_immediate_before_result(self):
        self.bot.process('1221647274', 'Fresh AI jobs in Bangalore')
        self.assertEqual(self.api.sent[0], ('1221647274', 'Thinking…'))
        self.assertTrue(self.api.sent[1][1].startswith('1. AI Engineer'))

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

    def test_help_is_jobmaster_not_generic_assistant(self):
        self.bot.process('42', '/start')
        self.assertEqual(
            self.api.sent[-1][1],
            'JobMaster provides verified jobs and live job-market insights. '
            'Ask naturally in any sentence.',
        )


if __name__ == '__main__':
    unittest.main()
