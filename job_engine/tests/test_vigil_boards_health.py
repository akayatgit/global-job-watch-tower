"""Unit tests for the /health board's JobMaster voice-AI status line.

Ashok asked (2026-08-05) whether OPENAI_API_KEY is even set on his laptop —
this line lets him check from Telegram (`/health`) instead of opening a
terminal. Pure local env checks, no network, no model call.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app import config, vigil_boards


class VoiceStatusLabelTests(unittest.TestCase):
    def test_on_when_flag_default_and_key_present(self):
        with patch.dict('os.environ', {}, clear=False):
            import os

            os.environ.pop('JOBMASTER_VOICE_LLM', None)
            with patch.object(config, 'OPENAI_API_KEY', 'sk-test'):
                self.assertEqual(vigil_boards._voice_status_label(), 'ON (OPENAI_API_KEY set)')

    def test_off_when_key_missing(self):
        with patch.dict('os.environ', {'JOBMASTER_VOICE_LLM': 'true'}):
            with patch.object(config, 'OPENAI_API_KEY', ''):
                self.assertEqual(vigil_boards._voice_status_label(), 'OFF (no OPENAI_API_KEY)')

    def test_off_when_flag_disabled_even_with_key(self):
        with patch.dict('os.environ', {'JOBMASTER_VOICE_LLM': 'false'}):
            with patch.object(config, 'OPENAI_API_KEY', 'sk-test'):
                self.assertEqual(
                    vigil_boards._voice_status_label(),
                    'OFF (disabled via JOBMASTER_VOICE_LLM)',
                )


class BoardHealthIncludesVoiceStatusTests(unittest.TestCase):
    def test_board_health_reports_voice_status_line(self):
        fake_payload = {
            'vitals': {'heat_c': 55, 'heat_label': 'Warm'},
            'recent_events': [],
        }
        with patch.object(vigil_boards, '_get', return_value=fake_payload):
            with patch.dict('os.environ', {'JOBMASTER_VOICE_LLM': 'true'}):
                with patch.object(config, 'OPENAI_API_KEY', ''):
                    text = vigil_boards._board_health()
        self.assertIn('JobMaster voice AI: OFF (no OPENAI_API_KEY)', text)


if __name__ == '__main__':
    unittest.main()
