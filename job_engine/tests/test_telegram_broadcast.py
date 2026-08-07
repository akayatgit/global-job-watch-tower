"""Owner push-notification / broadcast-list tests (kanban 2026-08-07).

Ashok's spec, clarified 2026-08-07: "everyone who are guests is the only
condition" — every chat that has EVER messaged JobMaster as a guest joins
the broadcast list, not only one that literally tapped /start; 3
consecutive unanswered pushes temporarily drops them; any activity from
them (anywhere) brings them straight back."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from app import telegram_broadcast
from app.telegram_sessions import TelegramSessionStore


class BroadcastSubscriberLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = TelegramSessionStore(Path(self.tmp.name) / 'bot.db')

    def tearDown(self):
        self.tmp.cleanup()

    def test_any_activity_from_a_brand_new_chat_enrolls_them_too(self):
        # Ashok (2026-08-07): a guest whose first-ever message is a fully
        # specified query never routes through ButtonFlow.start() at all —
        # "everyone who are guests is the only condition" means ordinary
        # activity is enough, not only a literal /start tap.
        telegram_broadcast.record_activity(self.sessions, 'first-message-was-a-search')
        self.assertEqual(
            self.sessions.list_active_broadcast_subscribers(),
            ['first-message-was-a-search'],
        )

    def test_tapping_start_adds_the_chat_to_the_broadcast_list(self):
        telegram_broadcast.record_start(self.sessions, 'chat-1')
        self.assertEqual(self.sessions.list_active_broadcast_subscribers(), ['chat-1'])

    def test_explicit_stop_removes_the_chat(self):
        telegram_broadcast.record_start(self.sessions, 'chat-1')
        telegram_broadcast.stop(self.sessions, 'chat-1')
        self.assertEqual(self.sessions.list_active_broadcast_subscribers(), [])

    def test_any_activity_reactivates_a_stopped_chat(self):
        telegram_broadcast.record_start(self.sessions, 'chat-1')
        telegram_broadcast.stop(self.sessions, 'chat-1')
        telegram_broadcast.record_activity(self.sessions, 'chat-1')
        self.assertEqual(self.sessions.list_active_broadcast_subscribers(), ['chat-1'])

    def test_three_unanswered_pushes_temporarily_drops_the_subscriber(self):
        telegram_broadcast.record_start(self.sessions, 'chat-1')
        push_id = self.sessions.create_broadcast_push(text='hello')
        self.sessions.record_broadcast_sent(push_id, 'chat-1')
        self.sessions.record_broadcast_sent(push_id, 'chat-1')
        self.assertEqual(self.sessions.list_active_broadcast_subscribers(), ['chat-1'])
        self.sessions.record_broadcast_sent(push_id, 'chat-1')
        self.assertEqual(self.sessions.list_active_broadcast_subscribers(), [])

    def test_any_response_between_pushes_resets_the_unanswered_counter(self):
        telegram_broadcast.record_start(self.sessions, 'chat-1')
        push_id = self.sessions.create_broadcast_push(text='hello')
        self.sessions.record_broadcast_sent(push_id, 'chat-1')
        self.sessions.record_broadcast_sent(push_id, 'chat-1')
        telegram_broadcast.record_activity(self.sessions, 'chat-1')  # guest replies
        self.sessions.record_broadcast_sent(push_id, 'chat-1')
        self.sessions.record_broadcast_sent(push_id, 'chat-1')
        # Only 2 unanswered since the reply — still active.
        self.assertEqual(self.sessions.list_active_broadcast_subscribers(), ['chat-1'])


class SendBroadcastTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = TelegramSessionStore(Path(self.tmp.name) / 'bot.db')
        self.sent: list[tuple[str, str, str, list]] = []

    def tearDown(self):
        self.tmp.cleanup()

    def _send(self, chat_id, text, photo_file_id, keyboard):
        self.sent.append((chat_id, text, photo_file_id, keyboard))

    def test_sends_to_every_active_subscriber_with_like_and_stop_buttons(self):
        telegram_broadcast.record_start(self.sessions, 'a')
        telegram_broadcast.record_start(self.sessions, 'b')
        result = telegram_broadcast.send_broadcast(
            self.sessions, self._send, text='New AI/ML openings just dropped!',
            sleep=lambda _s: None,
        )
        self.assertEqual(result['sent'], 2)
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['failed'], 0)
        chat_ids = {row[0] for row in self.sent}
        self.assertEqual(chat_ids, {'a', 'b'})
        _chat, text, _photo, keyboard = self.sent[0]
        self.assertIn('New AI/ML openings', text)
        self.assertIn('Tip: tap 👍', text)
        labels = [label for row in keyboard for label, _data in row]
        self.assertIn('👍 Like', labels)
        self.assertIn('🔕 Stop notifications', labels)

    def test_never_reaches_a_stopped_or_never_started_chat(self):
        telegram_broadcast.record_start(self.sessions, 'a')
        telegram_broadcast.stop(self.sessions, 'a')
        result = telegram_broadcast.send_broadcast(
            self.sessions, self._send, text='hi', sleep=lambda _s: None,
        )
        self.assertEqual(result['total'], 0)
        self.assertEqual(self.sent, [])

    def test_a_failed_send_is_counted_but_does_not_stop_the_rest(self):
        telegram_broadcast.record_start(self.sessions, 'a')
        telegram_broadcast.record_start(self.sessions, 'b')

        def flaky_send(chat_id, text, photo_file_id, keyboard):
            if chat_id == 'a':
                raise OSError('boom')
            self.sent.append((chat_id, text, photo_file_id, keyboard))

        result = telegram_broadcast.send_broadcast(
            self.sessions, flaky_send, text='hi', sleep=lambda _s: None,
        )
        self.assertEqual(result['sent'], 1)
        self.assertEqual(result['failed'], 1)
        self.assertEqual(len(self.sent), 1)

    def test_a_successful_send_still_counts_toward_the_unanswered_cap(self):
        telegram_broadcast.record_start(self.sessions, 'a')
        for _ in range(3):
            telegram_broadcast.send_broadcast(
                self.sessions, self._send, text='hi', sleep=lambda _s: None,
            )
        self.assertEqual(self.sessions.list_active_broadcast_subscribers(), [])

    def test_latest_push_stats_reflect_recipients_and_likes(self):
        telegram_broadcast.record_start(self.sessions, 'a')
        telegram_broadcast.send_broadcast(
            self.sessions, self._send, text='hi', sleep=lambda _s: None,
        )
        latest = self.sessions.latest_broadcast_push()
        self.assertEqual(latest['text'], 'hi')
        self.assertEqual(latest['recipient_count'], 1)
        self.assertEqual(latest['like_count'], 0)
        self.sessions.like_broadcast_push(latest['id'])
        self.assertEqual(self.sessions.latest_broadcast_push()['like_count'], 1)


class BackfillFromHistoryTests(unittest.TestCase):
    """azr0099, supriyamk, cryptoonz (2026-08-07): guests who chatted with
    JobMaster BEFORE the broadcast table existed must be on the list from
    the very next bot startup, without messaging again first."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / 'bot.db'

    def tearDown(self):
        self.tmp.cleanup()

    def test_reopening_the_store_backfills_guests_with_conversation_history(self):
        sessions = TelegramSessionStore(self.db_path)
        sessions.finalize_guest_conversation(1, 'azr0099', 'azr0099', 'hi', 'hello')
        self.assertEqual(sessions.list_active_broadcast_subscribers(), [])

        reopened = TelegramSessionStore(self.db_path)
        self.assertIn('azr0099', reopened.list_active_broadcast_subscribers())

    def test_backfill_also_picks_up_guest_profiles_and_onboarding_sessions(self):
        sessions = TelegramSessionStore(self.db_path)
        sessions.save_guest_profile(
            'supriyamk', role_label='AI Engineer', role_family='ai',
            role_keywords=['ai'], experience='fresher', city='chennai',
        )
        sessions.save_onboarding('cryptoonz', {'stage': 'city'})

        reopened = TelegramSessionStore(self.db_path)
        subscribers = set(reopened.list_active_broadcast_subscribers())
        self.assertIn('supriyamk', subscribers)
        self.assertIn('cryptoonz', subscribers)

    def test_backfill_never_overrides_an_already_tracked_stopped_subscriber(self):
        sessions = TelegramSessionStore(self.db_path)
        sessions.finalize_guest_conversation(1, 'chat-1', '', 'hi', 'hello')
        telegram_broadcast.record_start(sessions, 'chat-1')
        telegram_broadcast.stop(sessions, 'chat-1')

        reopened = TelegramSessionStore(self.db_path)
        self.assertEqual(reopened.list_active_broadcast_subscribers(), [])

    def test_backfill_excludes_the_owner_chat_id(self):
        sessions = TelegramSessionStore(self.db_path)
        sessions.set_state('telegram_command_owner_ids', 'owner-1')
        sessions.finalize_guest_conversation(1, 'owner-1', 'ashok', 'hi', 'hello')

        reopened = TelegramSessionStore(self.db_path)
        self.assertNotIn('owner-1', reopened.list_active_broadcast_subscribers())


if __name__ == '__main__':
    unittest.main()
