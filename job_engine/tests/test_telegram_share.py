"""One-tap "Share JobMaster" link builder tests (kanban 2026-08-07)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import telegram_share
from app.telegram_sessions import TelegramSessionStore


class ShareLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = TelegramSessionStore(Path(self.tmp.name) / 'bot.db')

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_bot_username_known_yields_no_link(self):
        with patch.dict('os.environ', {}, clear=False):
            import os
            os.environ.pop('TELEGRAM_BOT_USERNAME', None)
            self.assertEqual(telegram_share.bot_link(self.sessions), '')
            self.assertEqual(telegram_share.share_button_url(self.sessions), '')

    def test_bot_username_from_session_state_builds_a_share_link(self):
        self.sessions.set_state('telegram_bot_username', 'vigil_akay_bot')
        link = telegram_share.bot_link(self.sessions)
        self.assertEqual(link, 'https://t.me/vigil_akay_bot')
        url = telegram_share.share_button_url(self.sessions)
        self.assertTrue(url.startswith('https://t.me/share/url?'))
        self.assertIn('vigil_akay_bot', url)

    def test_explicit_bot_username_overrides_stored_state(self):
        self.sessions.set_state('telegram_bot_username', 'stored_bot')
        url = telegram_share.share_button_url(self.sessions, bot_username='explicit_bot')
        self.assertIn('explicit_bot', url)
        self.assertNotIn('stored_bot', url)

    def test_role_label_personalizes_the_share_message(self):
        self.sessions.set_state('telegram_bot_username', 'vigil_akay_bot')
        generic = telegram_share.share_button_url(self.sessions)
        personalized = telegram_share.share_button_url(self.sessions, role_label='AI/ML')
        self.assertNotEqual(generic, personalized)
        self.assertIn('AI', personalized)

    def test_env_var_fallback_when_state_is_empty(self):
        with patch.dict('os.environ', {'TELEGRAM_BOT_USERNAME': 'env_bot'}):
            url = telegram_share.share_button_url(self.sessions)
            self.assertIn('env_bot', url)


if __name__ == '__main__':
    unittest.main()
