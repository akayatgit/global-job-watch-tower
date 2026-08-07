"""Owner push notifications / broadcasts (kanban card 2026-08-07).

Ashok's spec: "everyone who are guests is the only condition" — every chat
that has ever messaged JobMaster as a guest (not only one that literally
tapped /start) is a broadcast subscriber (this is the retention/
re-engagement list — "keep reminding them JobMaster exists"), reachable via
an Ashok-only /push command with text, an image, or both. Guests from
before this feature shipped are backfilled from existing conversation/
profile history (see TelegramSessionStore._backfill_broadcast_subscribers)
so they don't have to message again first. To avoid looking like a spam bot
to Telegram (and to guests), a subscriber who receives
MAX_UNANSWERED_PUSHES broadcasts in a row with zero interaction in between
is temporarily dropped from the list — any message or button tap from them
(anywhere in JobMaster, not just a push reply) brings them straight back
in, no re-opt-in flow needed.
"""

from __future__ import annotations

import time
from typing import Any, Callable

MAX_UNANSWERED_PUSHES = 3
SEND_DELAY_S = 0.05  # ~20 sends/sec, safely under Telegram's ~30/sec cap

BROADCAST_HINT = '\n\nTip: tap 👍 if this is useful, or 🔕 below anytime to stop these updates.'


def record_start(sessions, chat_id: str) -> None:
    sessions.record_broadcast_start(chat_id)


def record_activity(sessions, chat_id: str) -> None:
    sessions.record_broadcast_activity(chat_id)


def stop(sessions, chat_id: str) -> None:
    sessions.stop_broadcast(chat_id)


def send_broadcast(
    sessions,
    send_fn: Callable[[str, str, str, list[list[tuple[str, str]]] | None], None],
    *,
    text: str,
    photo_file_id: str = '',
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Fan out one push to every currently active broadcast subscriber.

    send_fn(chat_id, text, photo_file_id, keyboard) is the caller's actual
    Telegram delivery — kept injectable so this stays unit-testable without
    a real bot token.
    """
    subscribers = sessions.list_active_broadcast_subscribers()
    push_id = sessions.create_broadcast_push(text=text, photo_file_id=photo_file_id)
    keyboard = [[('👍 Like', f'push:like:{push_id}'), ('🔕 Stop notifications', 'push:stop')]]
    full_text = f'{text}{BROADCAST_HINT}'
    sent = 0
    failed = 0
    for index, chat_id in enumerate(subscribers):
        try:
            send_fn(chat_id, full_text, photo_file_id, keyboard)
            sessions.record_broadcast_sent(push_id, chat_id, max_unanswered=MAX_UNANSWERED_PUSHES)
            sent += 1
        except Exception:
            failed += 1
        if index < len(subscribers) - 1:
            sleep(SEND_DELAY_S)
    return {'push_id': push_id, 'sent': sent, 'failed': failed, 'total': len(subscribers)}
