"""One-tap "Share JobMaster" hook — word-of-mouth GTM (Ashok, 2026-08-07).

The Open Gate change (kanban card #13) made word of mouth JobMaster's real
growth channel. This gives every guest who just saw a good result a
frictionless way to forward the bot to a friend.

Deliberately does NOT use Telegram's `switch_inline_query` button — that
requires inline mode to be enabled for this bot via @BotFather, which is not
set up. Instead this uses `https://t.me/share/url` — a public, client-side
Telegram link that opens the native "Forward to..." chat picker for
arbitrary text. No bot-side API feature or extra permission is required, and
tapping it never produces a callback_query (the OS opens the URL directly),
so there is no backend handling needed for the tap itself.
"""

from __future__ import annotations

import os
import urllib.parse

# Populated from Telegram's own getMe() at bot startup (see
# scripts/telegram_job_bot.py::run) so the link always points at whichever
# bot account is actually live — never hardcoded. TELEGRAM_BOT_USERNAME is a
# fallback for local/dev runs (e.g. smoke tests) where getMe() output isn't
# persisted through this exact state key.
BOT_USERNAME_STATE_KEY = 'telegram_bot_username'

SHARE_MESSAGE_GENERIC = (
    'I found real, verified jobs (with LinkedIn links) for freshers and '
    'interns through JobMaster on Telegram \u2014 free, no signup, just tap '
    'and search. Try it:'
)
SHARE_MESSAGE_WITH_ROLE = (
    'I found real {role_label} openings for freshers/interns through '
    'JobMaster on Telegram \u2014 free, no signup, just tap and search. Try it:'
)


def _bot_username(sessions, *, bot_username: str = '') -> str:
    explicit = (bot_username or '').strip()
    if explicit:
        return explicit
    stored = sessions.get_state(BOT_USERNAME_STATE_KEY, '') if sessions else ''
    if stored.strip():
        return stored.strip()
    return (os.environ.get('TELEGRAM_BOT_USERNAME') or '').strip()


def bot_link(sessions, *, bot_username: str = '') -> str:
    username = _bot_username(sessions, bot_username=bot_username)
    return f'https://t.me/{username}' if username else ''


def share_button_url(sessions, *, role_label: str = '', bot_username: str = '') -> str:
    """Returns a `t.me/share/url` link, or '' when the bot username is not
    yet known (e.g. before the first live startup) — callers must skip the
    button entirely in that case rather than show a dead link."""
    link = bot_link(sessions, bot_username=bot_username)
    if not link:
        return ''
    message = (
        SHARE_MESSAGE_WITH_ROLE.format(role_label=role_label)
        if role_label
        else SHARE_MESSAGE_GENERIC
    )
    query = urllib.parse.urlencode({'url': link, 'text': message})
    return f'https://t.me/share/url?{query}'
