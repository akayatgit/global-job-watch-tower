"""Unit tests for the JobMaster voice layer (Ashok's 1A decision, 2026-08-05).

Covers the fact-lock validator (`validate_voice`) in isolation and the
`VoiceLayer.speak` best-effort pass with a stub OpenAI client — no network,
no real credentials.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app import config
from app.telegram_voice import VoiceLayer, validate_voice

JOB_REPLY = (
    '1. AI Engineer — Acme — Fresher\n'
    'https://www.linkedin.com/jobs/view/4448000001/\n\n'
    '2. ML Engineer — Globex — 1–2 years\n'
    'https://www.linkedin.com/jobs/view/4448000002/'
)


class FakeChoice:
    def __init__(self, content: str):
        self.message = type('Msg', (), {'content': content})()


class FakeCompletions:
    def __init__(self, content: str | Exception):
        self._content = content

    def create(self, **_kwargs):
        if isinstance(self._content, Exception):
            raise self._content
        return type('Resp', (), {'choices': [FakeChoice(self._content)]})()


class FakeChat:
    def __init__(self, content: str | Exception):
        self.completions = FakeCompletions(content)


class FakeOpenAIClient:
    def __init__(self, content: str | Exception):
        self.chat = FakeChat(content)


class ValidateVoiceTests(unittest.TestCase):
    def test_accepts_lines_preserved_with_added_warmth(self):
        candidate = (
            'Great news! Here is what I found for you:\n\n' + JOB_REPLY +
            '\n\nLet me know if you want more.'
        )
        self.assertTrue(validate_voice(JOB_REPLY, candidate))

    def test_rejects_when_a_fact_line_is_altered(self):
        candidate = JOB_REPLY.replace('Acme', 'Acme Corp International')
        self.assertFalse(validate_voice(JOB_REPLY, candidate))

    def test_rejects_when_a_fact_line_is_dropped(self):
        candidate = '1. AI Engineer — Acme — Fresher\nhttps://www.linkedin.com/jobs/view/4448000001/'
        self.assertFalse(validate_voice(JOB_REPLY, candidate))

    def test_rejects_when_lines_are_reordered(self):
        lines = JOB_REPLY.split('\n\n')
        candidate = '\n\n'.join(reversed(lines))
        self.assertFalse(validate_voice(JOB_REPLY, candidate))

    def test_rejects_new_url_not_in_original(self):
        candidate = JOB_REPLY + '\nhttps://www.linkedin.com/jobs/view/9999999999/'
        self.assertFalse(validate_voice(JOB_REPLY, candidate))

    def test_rejects_empty_candidate(self):
        self.assertFalse(validate_voice(JOB_REPLY, ''))
        self.assertFalse(validate_voice(JOB_REPLY, '   '))

    def test_accepts_identical_passthrough(self):
        self.assertTrue(validate_voice(JOB_REPLY, JOB_REPLY))


class VoiceLayerTests(unittest.TestCase):
    def test_disabled_without_api_key_returns_original(self):
        with patch.object(config, 'OPENAI_API_KEY', ''):
            layer = VoiceLayer(client_factory=lambda: self.fail('must not call model'))
            self.assertEqual(layer.speak(JOB_REPLY), JOB_REPLY)

    def test_disabled_via_flag_returns_original_even_with_key(self):
        with patch.object(config, 'OPENAI_API_KEY', 'test-key'):
            layer = VoiceLayer(
                enabled=False,
                client_factory=lambda: self.fail('must not call model'),
            )
            self.assertEqual(layer.speak(JOB_REPLY), JOB_REPLY)

    def test_enabled_with_compliant_candidate_returns_voiced_text(self):
        voiced = 'Nice — found a couple of matches:\n\n' + JOB_REPLY
        with patch.object(config, 'OPENAI_API_KEY', 'test-key'):
            layer = VoiceLayer(client_factory=lambda: FakeOpenAIClient(voiced))
            self.assertEqual(layer.speak(JOB_REPLY), voiced)

    def test_enabled_with_noncompliant_candidate_falls_back(self):
        tampered = JOB_REPLY.replace('Acme', 'FakeCo')
        with patch.object(config, 'OPENAI_API_KEY', 'test-key'):
            layer = VoiceLayer(client_factory=lambda: FakeOpenAIClient(tampered))
            self.assertEqual(layer.speak(JOB_REPLY), JOB_REPLY)

    def test_enabled_with_model_exception_falls_back(self):
        with patch.object(config, 'OPENAI_API_KEY', 'test-key'):
            layer = VoiceLayer(
                client_factory=lambda: FakeOpenAIClient(RuntimeError('timeout')),
            )
            self.assertEqual(layer.speak(JOB_REPLY), JOB_REPLY)

    def test_blank_reply_never_calls_model(self):
        with patch.object(config, 'OPENAI_API_KEY', 'test-key'):
            layer = VoiceLayer(client_factory=lambda: self.fail('must not call model'))
            self.assertEqual(layer.speak(''), '')
            self.assertEqual(layer.speak('   '), '   ')


if __name__ == '__main__':
    unittest.main()
