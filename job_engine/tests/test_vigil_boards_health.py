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


class BoardHealthVerificationQueueTests(unittest.TestCase):
    """Checked-only law (2026-08-14): /health shows how many jobs still wait
    for detail verification — the queue the full-mode drain is working."""

    def _render(self, payload):
        with patch.object(vigil_boards, '_get', return_value=payload):
            with patch.dict('os.environ', {'JOBMASTER_VOICE_LLM': 'false'}):
                return vigil_boards._board_health()

    def test_verification_queue_line_shows_both_counts(self):
        text = self._render({
            'vitals': {'heat_c': 47, 'heat_label': 'Cool'},
            'verification': {'unchecked': 143, 'checked': 892},
            'recent_events': [],
        })
        self.assertIn('Verification queue 143 unchecked · 892 checked', text)

    def test_missing_verification_payload_never_crashes_the_board(self):
        text = self._render({
            'vitals': {'heat_c': 47, 'heat_label': 'Cool'},
            'recent_events': [],
        })
        self.assertIn('Verification queue — unchecked · — checked', text)


class BoardHealthStallHonestyTests(unittest.TestCase):
    """2026-08-13: day-old pulses with no timestamps + 'Tower healthy' hid a
    full engine outage. The board must show pulse ages and the stall reason."""

    def _render(self, payload):
        with patch.object(vigil_boards, '_get', return_value=payload):
            with patch.dict('os.environ', {'JOBMASTER_VOICE_LLM': 'false'}):
                return vigil_boards._board_health()

    def test_recent_pulses_carry_relative_age(self):
        from datetime import datetime, timedelta, timezone

        old_ts = (datetime.now(timezone.utc) - timedelta(hours=26)).isoformat()
        text = self._render({
            'vitals': {'heat_c': 47, 'heat_label': 'Cool'},
            'recent_events': [{
                'id': 1,
                'kind': 'ollama_filter',
                'message': 'kept 4/7 for junior software developer',
                'created_at': old_ts,
            }],
        })
        self.assertIn('ollama_filter: kept 4/7 for junior software developer · 26h ago', text)

    def test_stall_detail_line_shown_when_engine_dead(self):
        text = self._render({
            'vitals': {
                'heat_c': 47,
                'heat_label': 'Cool',
                'alert_label': 'Collection stalled — engine not running',
                'stall_detail': '"Junior Software Developer" has shown as running for 26h',
            },
            'recent_events': [],
        })
        self.assertIn('Alert: Collection stalled — engine not running', text)
        self.assertIn('Stalled: "Junior Software Developer" has shown as running for 26h', text)


class RelAgeTests(unittest.TestCase):
    def test_rel_age_buckets(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        self.assertEqual(vigil_boards._rel_age(now.isoformat()), 'just now')
        self.assertEqual(vigil_boards._rel_age((now - timedelta(minutes=20)).isoformat()), '20m ago')
        self.assertEqual(vigil_boards._rel_age((now - timedelta(hours=26)).isoformat()), '26h ago')
        self.assertEqual(vigil_boards._rel_age((now - timedelta(days=3)).isoformat()), '3d ago')
        self.assertEqual(vigil_boards._rel_age(None), '')
        self.assertEqual(vigil_boards._rel_age('not-a-date'), '')


if __name__ == '__main__':
    unittest.main()
