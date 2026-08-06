#!/usr/bin/env python3
"""Dedicated Telegram ingress for JobMaster.

Hermes does not receive this bot's updates. Natural-language understanding is
constrained to intent extraction; Watch Tower APIs and deterministic formatters
own every job, link, number, and comparison sent to users.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import signal
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.cities import city_label  # noqa: E402
from app.telegram_buttons import BTN_PREFIX, EXPERIENCE_LABELS, ButtonFlow, ButtonReply  # noqa: E402
from app.telegram_job_search import (  # noqa: E402
    GREETING_RE,
    MORE_RE,
    PAGE_SIZE,
    RESET_RE,
    ROLE_FAMILY_LABELS,
    JobMasterEngine,
)
from app.telegram_waitlist import list_waitlist, waitlist_count  # noqa: E402
from app.telegram_guests import (  # noqa: E402
    DEFAULT_TTL_MINUTES,
    MAX_TTL_MINUTES as MAX_GUEST_MINUTES,
    add_guest,
    add_username,
    block_guest,
    block_username,
    describe_access,
    format_ttl,
    is_allowed,
    list_blocked,
    list_guests,
    list_usernames,
    observe_identity,
)
from app.telegram_sessions import (  # noqa: E402
    AmbiguousTelegramIdentity,
    TelegramSessionStore,
)
from app.telegram_voice import VoiceLayer  # noqa: E402
from app.vigil_boards import render_board  # noqa: E402

HERMES_ENV = Path.home() / '.hermes' / '.env'
HEALTH_FILE = ROOT / '.data' / 'jobmaster_telegram_health.json'
VERSION_FILE = ROOT.parent / 'VERSION'
LOG = logging.getLogger('jobmaster-telegram')
STOP = False
HEALTH_LOCK = threading.Lock()
SMOKE_LINK_RE = re.compile(r'https://www\.linkedin\.com/jobs/view/\d+/')
SMOKE_ROW_RE = re.compile(r'^\d+\. .+ — .+ — .+$', re.MULTILINE)
SMOKE_BANNED = ('mcp__', 'provider:', 'model:', 'endpoint:', 'watch tower data')
COMMAND_RE = re.compile(r'^/([a-z0-9_]+)(?:@[a-z0-9_]+)?(?:\s+(.*))?$', re.I)
OWNER_BOARD_COMMANDS = {
    'towerinsights': 'tower',
    'health': 'health',
    'hiringsignals': 'signals',
    'hiringinsights': 'signals',
    'signals': 'signals',
    'searches': 'searches',
    'watchlist': 'watchlist',
    'fresh': 'fresh',
    'brief': 'brief',
    'boards': 'help',
}
OWNER_QUERY_COMMANDS = {
    'stats': lambda arg: f'How many {arg or ""} jobs in the past 24 hours?'.strip(),
    'governmentjobs': lambda _arg: 'Government jobs',
}
OWNER_MANAGEMENT_COMMANDS = frozenset({
    'allowguest',
    'allow',
    'allowuser',
    'blockguest',
    'block',
    'revoke',
    'revokeuser',
    'guests',
    'guestlist',
    'history',
    'guestprofile',
    'waitlist',
    'checkaccess',
})
# Ashok-only self-test toggle: no second phone needed to see the guest
# experience. Always dispatched off the REAL owner check (never the
# simulated one) so this pair of commands can never lock him out of his
# own chat — see _toggle_role_switch.
OWNER_ROLE_SWITCH_COMMANDS = frozenset({'actasguest', 'actasowner'})
OWNER_COMMANDS = frozenset((
    *OWNER_BOARD_COMMANDS,
    *OWNER_QUERY_COMMANDS,
    *OWNER_MANAGEMENT_COMMANDS,
    *OWNER_ROLE_SWITCH_COMMANDS,
))
OWNER_MENU = [
    {'command': 'allowguest', 'description': 'Un-block / VIP a person'},
    {'command': 'blockguest', 'description': 'Block a person (public by default)'},
    {'command': 'guests', 'description': 'Access dashboard'},
    {'command': 'history', 'description': 'Guest conversation history'},
    {'command': 'guestprofile', 'description': 'Guest role/experience/city'},
    {'command': 'checkaccess', 'description': 'Why can/can\'t a person text?'},
    {'command': 'waitlist', 'description': 'Experienced-hire email waitlist'},
    {'command': 'actasguest', 'description': 'Test this chat as a guest'},
    {'command': 'actasowner', 'description': 'Back to owner mode'},
    {'command': 'stats', 'description': 'Live job count · add a role'},
    {'command': 'towerinsights', 'description': 'Tower insights'},
    {'command': 'health', 'description': 'Tower health'},
    {'command': 'hiringsignals', 'description': 'Hiring signals'},
    {'command': 'searches', 'description': 'Roles being watched'},
    {'command': 'watchlist', 'description': 'Watched companies'},
    {'command': 'fresh', 'description': 'Freshest catches'},
    {'command': 'governmentjobs', 'description': 'Government jobs'},
    {'command': 'brief', 'description': 'Daily hiring brief'},
    {'command': 'boards', 'description': 'VIGIL command menu'},
]


def _utf16_units(text: str) -> int:
    return len(str(text).encode('utf-16-le')) // 2


def _truncate_utf16(text: str, max_units: int) -> str:
    value = str(text or '')
    if _utf16_units(value) <= max_units:
        return value
    suffix = '…'
    budget = max(0, max_units - _utf16_units(suffix))
    out: list[str] = []
    used = 0
    for character in value:
        units = _utf16_units(character)
        if used + units > budget:
            break
        out.append(character)
        used += units
    return ''.join(out) + suffix


def _telegram_chunks(text: str, max_units: int = 3800) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    used = 0
    for character in str(text or ''):
        units = _utf16_units(character)
        if current and used + units > max_units:
            chunks.append(''.join(current))
            current = []
            used = 0
        current.append(character)
        used += units
    if current:
        chunks.append(''.join(current))
    return chunks


def load_env() -> dict[str, str]:
    values = dict(os.environ)
    if HERMES_ENV.exists():
        for line in HERMES_ENV.read_text(encoding='utf-8').splitlines():
            if not line or line.lstrip().startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return values


class TelegramAPI:
    def __init__(self, token: str):
        if not token:
            raise ValueError('TELEGRAM_BOT_TOKEN is required')
        self.base = f'https://api.telegram.org/bot{token}'

    def call(self, method: str, data: dict[str, Any] | None = None, timeout: int = 35) -> dict:
        body = urllib.parse.urlencode(data or {}).encode()
        req = urllib.request.Request(
            f'{self.base}/{method}',
            data=body,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        if not payload.get('ok'):
            raise RuntimeError(f'Telegram {method} failed: {payload.get("description", "unknown")}')
        return payload

    def send(self, chat_id: str, text: str) -> None:
        remaining = (text or '').strip()
        if not remaining:
            return
        for chunk in _telegram_chunks(remaining):
            self.call('sendMessage', {
                'chat_id': str(chat_id),
                'text': chunk,
                'disable_web_page_preview': 'true',
            })

    def send_keyboard(
        self,
        chat_id: str,
        text: str,
        keyboard: list[list[tuple[str, str]]] | None,
    ) -> None:
        """Send text with an inline keyboard attached to the LAST chunk only
        — a button-flow message is always short enough to be one chunk in
        practice, but this stays correct even if it ever isn't."""
        remaining = (text or '').strip()
        if not remaining:
            return
        chunks = _telegram_chunks(remaining)
        markup = None
        if keyboard:
            markup = json.dumps({
                'inline_keyboard': [
                    [{'text': label, 'callback_data': data} for label, data in row]
                    for row in keyboard
                ]
            })
        for index, chunk in enumerate(chunks):
            payload = {
                'chat_id': str(chat_id),
                'text': chunk,
                'disable_web_page_preview': 'true',
            }
            if markup is not None and index == len(chunks) - 1:
                payload['reply_markup'] = markup
            self.call('sendMessage', payload)

    def answer_callback(self, callback_query_id: str, text: str = '') -> None:
        try:
            data: dict[str, Any] = {'callback_query_id': callback_query_id}
            if text:
                data['text'] = text[:200]
            self.call('answerCallbackQuery', data)
        except Exception:
            # Cosmetic only (clears the tap's loading spinner) — never let a
            # failure here block delivering the actual reply.
            LOG.exception('answerCallbackQuery failed id=%s', callback_query_id)

    def updates(self, offset: int, timeout: int = 25) -> list[dict]:
        result = self.call(
            'getUpdates',
            {
                'offset': offset,
                'timeout': timeout,
                'allowed_updates': json.dumps(['message', 'callback_query']),
            },
            timeout=timeout + 10,
        )
        return result.get('result') or []


class JobMasterTelegramBot:
    def __init__(
        self,
        api: TelegramAPI,
        *,
        engine: JobMasterEngine | None = None,
        sessions: TelegramSessionStore | None = None,
        health_enabled: bool = True,
        owner_chat_ids: set[str] | None = None,
        board_renderer=None,
        voice: VoiceLayer | None = None,
    ):
        self.api = api
        self.sessions = sessions or TelegramSessionStore()
        self.engine = engine or JobMasterEngine(sessions=self.sessions)
        self.voice = voice or VoiceLayer()
        self.button_flow = ButtonFlow(self.engine, self.sessions)
        self.health_enabled = health_enabled
        self.owner_chat_ids = {str(chat_id) for chat_id in (owner_chat_ids or set())}
        self.board_renderer = board_renderer or render_board
        self._last_request: dict[str, float] = {}
        self._chat_locks: dict[str, threading.Lock] = {}
        self._chat_locks_guard = threading.Lock()
        self._queue_guard = threading.Lock()
        self._chat_queues: dict[str, deque[tuple[int, str, str, bool]]] = {}
        self._active_chats: set[str] = set()
        self._query_count = 0
        self._page_count = 0

    @staticmethod
    def _command(text: str) -> tuple[str, str] | None:
        match = COMMAND_RE.match((text or '').strip())
        if not match:
            return None
        return match.group(1).lower(), (match.group(2) or '').strip()

    @staticmethod
    def _identity(raw: str) -> tuple[str, str] | None:
        value = (raw or '').strip()
        if value.startswith('@'):
            handle = value[1:]
            if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}', handle):
                return 'username', handle
            return None
        if re.fullmatch(r'\d+', value):
            user_id = int(value)
            if 0 < user_id < 2**52:
                return 'user_id', value
            return None
        if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}', value):
            return 'username', value
        return None

    def _is_owner(self, chat_id: str) -> bool:
        """Real owner identity. Always used for message-queue acceptance so
        Ashok testing the guest experience (see _effective_is_owner) can
        never accidentally get himself silently dropped."""
        return str(chat_id) in self.owner_chat_ids

    def _is_simulating_guest(self, chat_id: str) -> bool:
        return self.sessions.get_state(f'simulate_guest:{chat_id}', '0') == '1'

    def _effective_is_owner(self, chat_id: str) -> bool:
        """Owner-ness for command authorization and guest-history recording
        only — this is the one thing /actasguest flips off, so Ashok's own
        chat sees exactly what a guest sees for commands and history."""
        return self._is_owner(chat_id) and not self._is_simulating_guest(chat_id)

    def _sender_allowed(self, chat_id: str, username: str = '') -> bool:
        return self._is_owner(chat_id) or is_allowed(chat_id, username)

    def _toggle_role_switch(self, chat_id: str, command: str) -> str:
        scope_chat_id: int | str = (
            int(chat_id) if str(chat_id).lstrip('-').isdigit() else chat_id
        )
        if command == 'actasguest':
            if self._is_simulating_guest(chat_id):
                return "Already testing as a guest. Send /actasowner to switch back."
            self.sessions.set_state(f'simulate_guest:{chat_id}', '1')
            try:
                self.api.call('deleteMyCommands', {
                    'scope': json.dumps({'type': 'chat', 'chat_id': scope_chat_id}),
                })
            except Exception:
                LOG.exception(
                    'failed to hide command menu for guest simulation chat=%s', chat_id,
                )
            return (
                'Testing mode ON. This chat now behaves exactly like a guest: '
                'the command menu is hidden, VIGIL/management commands are '
                "denied (you'll see the same reply a guest sees), and search "
                "conversations here are recorded like a guest's for /history "
                'and /guestprofile. Send /actasowner anytime to switch back.'
            )
        if not self._is_simulating_guest(chat_id):
            return 'Already in owner mode.'
        self.sessions.set_state(f'simulate_guest:{chat_id}', '0')
        try:
            self.api.call('setMyCommands', {
                'scope': json.dumps({'type': 'chat', 'chat_id': scope_chat_id}),
                'commands': json.dumps(OWNER_MENU),
            })
        except Exception:
            LOG.exception(
                'failed to restore command menu after guest simulation chat=%s', chat_id,
            )
        return 'Testing mode OFF. Command menu and full owner access are back.'

    def _owner_command_reply(
        self,
        chat_id: str,
        command: str,
        arg: str,
        *,
        update_id: int | None,
    ) -> str:
        if command in OWNER_MANAGEMENT_COMMANDS:
            return self._management_reply(chat_id, command, arg)
        if command in OWNER_BOARD_COMMANDS:
            days = None
            if arg:
                try:
                    days = int(arg.split()[0])
                except ValueError:
                    days = None
            return self.board_renderer(OWNER_BOARD_COMMANDS[command], days=days)
        query = OWNER_QUERY_COMMANDS[command](arg)
        try:
            return self.engine.handle(query, chat_id, update_id=update_id)
        except TypeError as exc:
            if 'update_id' not in str(exc):
                raise
            return self.engine.handle(query, chat_id)

    @staticmethod
    def _relative_age(timestamp: float) -> str:
        seconds = max(0, int(time.time() - float(timestamp)))
        if seconds < 60:
            return 'just now'
        minutes = seconds // 60
        if minutes < 60:
            return f'{minutes}m ago'
        hours = minutes // 60
        if hours < 24:
            return f'{hours}h ago'
        days = hours // 24
        return f'{days}d ago'

    def _management_reply(self, chat_id: str, command: str, arg: str) -> str:
        allow_commands = {'allowguest', 'allow', 'allowuser'}
        block_commands = {'blockguest', 'block', 'revoke', 'revokeuser'}
        if command == 'history':
            parts = (arg or '').split(maxsplit=1)
            if not parts:
                return 'Usage: /history <@username or Telegram ID> [1–40]'
            identity = self._identity(parts[0])
            if identity is None:
                return 'Use a valid Telegram @username or positive numeric Telegram ID.'
            identity_kind, identity_value = identity
            limit = 10
            if len(parts) >= 2:
                try:
                    limit = int(parts[1])
                except ValueError:
                    return 'History count must be a whole number from 1 to 40.'
                if limit < 1:
                    return 'History count must be a whole number from 1 to 40.'
                limit = min(limit, 40)
            lookup = (
                f'@{identity_value}'
                if identity_kind == 'username'
                else identity_value
            )
            try:
                history = self.sessions.conversation_history(lookup, limit=limit)
            except AmbiguousTelegramIdentity:
                return (
                    f'{lookup} has been used by more than one Telegram account. '
                    'Use the numeric Telegram ID to avoid exposing the wrong history.'
                )
            if not history:
                return (
                    f'No stored conversations for {lookup}. '
                    'History starts after this feature is deployed.'
                )
            lines = [
                f'CONVERSATION HISTORY · {lookup} · latest {len(history)}',
                'Compact summaries · request fewer conversations for more detail.',
                '',
            ]
            pair_budget = max(52, (3500 - _utf16_units('\n'.join(lines))) // len(history))
            for index, item in enumerate(history, 1):
                prefix = f"{index}. {self._relative_age(item['completed_at'])}"
                fixed_units = _utf16_units(prefix) + _utf16_units('\nGuest: \nJobMaster: \n')
                content_budget = max(12, pair_budget - fixed_units)
                user_budget = max(5, content_budget // 3)
                reply_budget = max(7, content_budget - user_budget)
                lines.extend([
                    prefix,
                    f"Guest: {_truncate_utf16(item['user_text'], user_budget)}",
                    f"JobMaster: {_truncate_utf16(item['bot_reply'], reply_budget)}",
                    '',
                ])
            return _truncate_utf16('\n'.join(lines).rstrip(), 3700)
        if command == 'guestprofile':
            parts = (arg or '').split()
            if not parts:
                return 'Usage: /guestprofile <@username or Telegram ID>'
            identity = self._identity(parts[0])
            if identity is None:
                return 'Use a valid Telegram @username or positive numeric Telegram ID.'
            identity_kind, identity_value = identity
            lookup = (
                f'@{identity_value}'
                if identity_kind == 'username'
                else identity_value
            )
            try:
                profile = self.sessions.get_guest_profile(lookup)
            except AmbiguousTelegramIdentity:
                return (
                    f'{lookup} has been used by more than one Telegram account. '
                    'Use the numeric Telegram ID to avoid exposing the wrong profile.'
                )
            if not profile:
                return (
                    f'No stored preferences for {lookup} yet — they have not '
                    'completed onboarding or a search.'
                )
            role = profile['role_label'] or 'not stated'
            experience = profile['experience'] or 'any'
            city = city_label(profile['city']) if profile['city'] else 'any'
            age = self._relative_age(profile['updated_at'])
            return (
                f'GUEST PROFILE · {lookup}\n'
                f'Role — {role}\n'
                f'Experience — {experience}\n'
                f'City — {city}\n'
                f'Last updated — {age}'
            )
        if command == 'checkaccess':
            parts = (arg or '').split()
            if not parts:
                return 'Usage: /checkaccess <@username or Telegram ID> [Telegram ID to compare]'
            identity = self._identity(parts[0])
            if identity is None:
                return 'Use a valid Telegram @username or positive numeric Telegram ID.'
            identity_kind, identity_value = identity
            user_id = identity_value if identity_kind == 'user_id' else ''
            username = identity_value if identity_kind == 'username' else ''
            if not user_id and len(parts) >= 2:
                # Lets Ashok check "is @handle really this person's numeric
                # id" (e.g. one he looked up via @userinfobot) in one shot,
                # instead of two separate lookups.
                second = self._identity(parts[1])
                if second and second[0] == 'user_id':
                    user_id = second[1]
            lookup = f'@{identity_value}' if identity_kind == 'username' else identity_value
            result = describe_access(user_id, username)
            verdict = 'ALLOWED ✅' if result['allowed'] else 'BLOCKED ⛔'
            return f'ACCESS CHECK · {lookup}\n{verdict}\n{result["reason"]}'
        if command == 'waitlist':
            limit = 20
            if arg.strip():
                try:
                    limit = max(1, min(int(arg.strip().split()[0]), 200))
                except ValueError:
                    limit = 20
            total = waitlist_count()
            entries = list_waitlist(limit=limit)
            if not entries:
                return 'WAITLIST · 0 people\nNo experienced-hire emails collected yet.'
            lines = [f'WAITLIST · {total} people · latest {len(entries)}', '']
            for index, item in enumerate(entries, 1):
                role = ROLE_FAMILY_LABELS.get(item.get('role_family', ''), item.get('role_family') or 'any role')
                exp = EXPERIENCE_LABELS.get(item.get('experience', ''), item.get('experience') or 'unspecified')
                age = self._relative_age(item.get('created_at', 0.0))
                lines.append(f"{index}. {item.get('email', '')} · {role} · {exp} · {age}")
            return _truncate_utf16('\n'.join(lines), 3700)
        if command in allow_commands:
            parts = (arg or '').split(maxsplit=2)
            if not parts:
                return 'Usage: /allowguest <@username or Telegram ID> [minutes] [name]'
            identity = JobMasterTelegramBot._identity(parts[0])
            if identity is None:
                return 'Use a valid Telegram @username or positive numeric Telegram ID.'
            identity_kind, target = identity
            if identity_kind == 'username':
                handle = target
                add_username(handle, added_by=chat_id)
                return f'Allowed @{handle}. Their next message will work.'
            minutes = DEFAULT_TTL_MINUTES
            label = ''
            if len(parts) >= 2:
                try:
                    minutes = float(parts[1])
                except ValueError:
                    return (
                        'Minutes must be a number from 1 to '
                        f'{int(MAX_GUEST_MINUTES)}.'
                    )
                if (
                    not math.isfinite(minutes)
                    or minutes < 1
                    or minutes > MAX_GUEST_MINUTES
                ):
                    return (
                        'Minutes must be a number from 1 to '
                        f'{int(MAX_GUEST_MINUTES)}.'
                    )
                label = parts[2] if len(parts) >= 3 else ''
            entry = add_guest(target, minutes=minutes, label=label, added_by=chat_id)
            duration = format_ttl(entry.get('minutes', minutes) * 60)
            return (
                f'Allowed {target} for {duration}.'
                + (f' Name: {label}.' if label else '')
            )
        if command in block_commands:
            raw_target = (arg or '').split(maxsplit=1)[0].strip()
            if not raw_target:
                return 'Usage: /blockguest <@username or Telegram ID>'
            identity = JobMasterTelegramBot._identity(raw_target)
            if identity is None:
                return 'Use a valid Telegram @username or positive numeric Telegram ID.'
            identity_kind, target = identity
            if identity_kind == 'user_id':
                if target == str(chat_id):
                    return 'Ashok’s owner access cannot be blocked.'
                block_guest(target, blocked_by=chat_id)
                return f'Blocked {target}. New messages will be ignored.'
            handle = target
            block_username(handle, blocked_by=chat_id)
            return f'Blocked @{handle}. New messages will be ignored.'

        # Open gate (2026-08-06): access is public now — /blockguest and
        # /blockuser are the only remaining gate, so that's what this
        # dashboard leads with. The named allow-list and temporary VIP
        # grants below still exist (mostly for un-blocking / notes) but no
        # longer decide who gets in.
        allowed = list_usernames()
        temporary = list_guests()
        blocked = list_blocked()
        lines = ['ACCESS: OPEN TO EVERYONE', 'Anyone who messages JobMaster is a guest.']
        if blocked['usernames'] or blocked['user_ids']:
            lines.append('')
            lines.append('Blocked')
            lines.extend(f'  · @{handle}' for handle in blocked['usernames'])
            lines.extend(f'  · {user_id}' for user_id in blocked['user_ids'])
        else:
            lines.append('')
            lines.append('Blocked: nobody.')
        if allowed:
            lines.append('')
            lines.append('Named (legacy allow-list, no longer required)')
            lines.extend(f"  · @{item['username']}" for item in allowed)
        if temporary:
            lines.append('')
            lines.append('Temporary VIP grants')
            for item in temporary:
                label = f" · {item['label']}" if item['label'] else ''
                lines.append(
                    f"  · {item['user_id']}{label} · {format_ttl(item['expires_in_s'])} left"
                )
        return '\n'.join(lines)

    def _configure_command_menu(self) -> bool:
        """Remove global commands and expose VIGIL operations only to Ashok."""
        try:
            for scope_type in ('default', 'all_private_chats'):
                self.api.call(
                    'deleteMyCommands',
                    {'scope': json.dumps({'type': scope_type})},
                )
            previous_owner_ids = {
                value
                for value in self.sessions.get_state(
                    'telegram_command_owner_ids',
                    '',
                ).split(',')
                if value
            }
            for old_chat_id in sorted(previous_owner_ids - self.owner_chat_ids):
                old_scope_id: int | str = (
                    int(old_chat_id)
                    if old_chat_id.lstrip('-').isdigit()
                    else old_chat_id
                )
                self.api.call(
                    'deleteMyCommands',
                    {
                        'scope': json.dumps({
                            'type': 'chat',
                            'chat_id': old_scope_id,
                        }),
                    },
                )
            for chat_id in sorted(self.owner_chat_ids):
                scope_chat_id: int | str = int(chat_id) if chat_id.lstrip('-').isdigit() else chat_id
                self.api.call(
                    'setMyCommands',
                    {
                        'scope': json.dumps({'type': 'chat', 'chat_id': scope_chat_id}),
                        'commands': json.dumps(OWNER_MENU),
                    },
                )
            self.sessions.set_state(
                'telegram_command_owner_ids',
                ','.join(sorted(self.owner_chat_ids)),
            )
            return bool(self.owner_chat_ids)
        except Exception:
            LOG.exception('Telegram owner command menu setup failed')
            return False

    def process(
        self,
        chat_id: str,
        text: str,
        *,
        acked: bool = False,
        update_id: int | None = None,
    ) -> None:
        with self._chat_locks_guard:
            lock = self._chat_locks.setdefault(str(chat_id), threading.Lock())
        with lock:
            self._process_locked(str(chat_id), text, acked=acked, update_id=update_id)

    def _safe_process(
        self,
        chat_id: str,
        text: str,
        *,
        acked: bool = False,
        update_id: int | None = None,
    ) -> bool:
        try:
            self.process(chat_id, text, acked=acked, update_id=update_id)
            return True
        except Exception as exc:
            LOG.exception('Telegram delivery failed chat=%s', chat_id)
            if self.health_enabled:
                self._write_health(status='degraded', error=str(exc)[:200])
            return False

    @staticmethod
    def _display_text(raw: str) -> str:
        """A button tap's durable queue value carries a NUL-byte sentinel
        (see BTN_PREFIX) that Telegram's own API would reject as text and
        that would render as an invisible artifact in /history — show a
        readable label instead. The raw sentinel value is only ever
        consumed internally by _process_locked/button_flow, never by a
        human."""
        if raw.startswith(BTN_PREFIX):
            return f'[tapped: {raw[len(BTN_PREFIX):]}]'
        return raw

    def _finalize_delivered(
        self,
        update_id: int,
        chat_id: str,
        username: str,
        text: str,
        reply: str,
    ) -> None:
        """Finish delivery without letting optional history strand a chat."""
        if self._effective_is_owner(chat_id):
            self.sessions.complete_update(update_id)
            return
        try:
            self.sessions.finalize_guest_conversation(
                update_id,
                chat_id,
                username,
                self._display_text(text),
                reply,
            )
        except Exception as exc:
            LOG.exception(
                'conversation history persistence failed chat=%s update=%s',
                chat_id,
                update_id,
            )
            if self.health_enabled:
                self._write_health(
                    status='degraded',
                    error=f'history persistence: {str(exc)[:160]}',
                )
            try:
                self.sessions.complete_update(update_id)
            except Exception:
                LOG.exception(
                    'delivered inbox cleanup failed chat=%s update=%s',
                    chat_id,
                    update_id,
                )

    def _process_queued(
        self,
        update_id: int,
        chat_id: str,
        username: str,
        text: str,
        *,
        acked: bool = False,
    ) -> bool:
        # NOTE: a reply already computed before a crash is replayed as plain
        # text here (no inline keyboard) — extremely rare window, and the
        # guest can still just tap /start again. Not worth persisting
        # keyboard layouts through a crash for this.
        prepared = self.sessions.load_update_reply(update_id)
        if not self._sender_allowed(chat_id, username):
            LOG.info(
                'dropped queued Telegram sender after access change chat=%s username=%s',
                chat_id,
                username or 'none',
            )
            self.sessions.complete_update(update_id)
            return True
        if prepared is not None:
            try:
                self.api.send(chat_id, prepared)
            except Exception as exc:
                LOG.exception('prepared Telegram delivery failed chat=%s', chat_id)
                if self.health_enabled:
                    self._write_health(status='degraded', error=str(exc)[:200])
                return False
            self._finalize_delivered(
                update_id,
                chat_id,
                username,
                text,
                prepared,
            )
            return True
        if self._safe_process(chat_id, text, acked=acked, update_id=update_id):
            reply = self.sessions.load_update_reply(update_id)
            if reply is not None:
                self._finalize_delivered(
                    update_id,
                    chat_id,
                    username,
                    text,
                    reply,
                )
            else:
                self.sessions.complete_update(update_id)
            return True
        return False

    def _enqueue_update(
        self,
        workers: ThreadPoolExecutor,
        update_id: int,
        chat_id: str,
        username: str,
        text: str,
        *,
        acked: bool = False,
    ) -> None:
        with self._queue_guard:
            queue = self._chat_queues.setdefault(chat_id, deque())
            queue.append((update_id, username, text, acked))
            if chat_id in self._active_chats:
                return
            self._active_chats.add(chat_id)
        workers.submit(self._drain_chat, workers, chat_id)

    def _drain_chat(self, workers: ThreadPoolExecutor, chat_id: str) -> None:
        retry_delay = 1
        failures = 0
        while not STOP:
            with self._queue_guard:
                queue = self._chat_queues.get(chat_id)
                if not queue:
                    self._active_chats.discard(chat_id)
                    self._chat_queues.pop(chat_id, None)
                    return
                update_id, username, text, acked = queue.popleft()
            if self._process_queued(
                update_id,
                chat_id,
                username,
                text,
                acked=acked,
            ):
                retry_delay = 1
                failures = 0
                continue
            with self._queue_guard:
                self._chat_queues.setdefault(chat_id, deque()).appendleft(
                    (update_id, username, text, acked)
                )
            failures += 1
            if failures >= 3:
                with self._queue_guard:
                    self._active_chats.discard(chat_id)
                timer = threading.Timer(
                    60,
                    self._resume_chat,
                    args=(workers, chat_id),
                )
                timer.daemon = True
                timer.start()
                return
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30)
        with self._queue_guard:
            self._active_chats.discard(chat_id)
            self._chat_queues.pop(chat_id, None)

    def _resume_chat(self, workers: ThreadPoolExecutor, chat_id: str) -> None:
        if STOP:
            return
        with self._queue_guard:
            if chat_id in self._active_chats or not self._chat_queues.get(chat_id):
                return
            self._active_chats.add(chat_id)
        try:
            workers.submit(self._drain_chat, workers, chat_id)
        except RuntimeError:
            with self._queue_guard:
                self._active_chats.discard(chat_id)

    def _pre_ack(self, chat_id: str, text: str) -> bool:
        clean = (text or '').strip()
        parsed = self._command(clean)
        if (
            not clean
            or clean.startswith(BTN_PREFIX)  # button taps reply instantly — no "Thinking…"
            or RESET_RE.match(clean)
            or clean.lower() in {'/start', '/help', 'help'}
            or (parsed and parsed[0] in OWNER_COMMANDS)
        ):
            return False
        try:
            self.api.send(chat_id, 'Thinking…')
            return True
        except Exception:
            LOG.exception('immediate acknowledgement failed chat=%s', chat_id)
            return False

    def _send_button_reply(
        self,
        chat_id: str,
        reply: ButtonReply,
        *,
        update_id: int | None = None,
    ) -> None:
        if update_id is not None and self.sessions.load_update_reply(update_id) is None:
            self.sessions.save_update_reply(update_id, reply.text)
        self.api.send_keyboard(chat_id, reply.text, reply.keyboard)

    def smoke(self, chat_id: str, query: str) -> None:
        """Send only a contract-valid grounded production search result."""
        reply = self.engine.handle(query, chat_id)
        low = reply.lower()
        links = SMOKE_LINK_RE.findall(reply)
        rows = SMOKE_ROW_RE.findall(reply)
        if (
            len(links) != PAGE_SIZE
            or len(rows) != PAGE_SIZE
            or len(set(links)) != PAGE_SIZE
            or any(marker in low for marker in SMOKE_BANNED)
        ):
            raise RuntimeError(
                f'production smoke contract failed: rows={len(rows)} links={len(links)}'
            )
        self.api.send(chat_id, 'Thinking…')
        self.api.send(chat_id, reply)

    def _process_locked(
        self,
        chat_id: str,
        text: str,
        *,
        acked: bool = False,
        update_id: int | None = None,
    ) -> None:
        clean = (text or '').strip()
        if not clean:
            return
        if clean.startswith(BTN_PREFIX):
            # A tapped inline-keyboard button, encoded through the same
            # durable per-chat pipeline as typed text (see the poll loop) —
            # a NUL prefix can never appear in a real Telegram text message,
            # so this can never collide with anything a guest actually types.
            button_reply = self.button_flow.handle_callback(chat_id, clean[len(BTN_PREFIX):])
            self._send_button_reply(chat_id, button_reply, update_id=update_id)
            if self.health_enabled:
                self._write_health(
                    status='running', last_result='ok', last_chat=chat_id, last_kind='button',
                )
            return
        parsed = self._command(clean)
        if parsed and parsed[0] in OWNER_COMMANDS:
            command, arg = parsed
            if command in OWNER_ROLE_SWITCH_COMMANDS and self._is_owner(chat_id):
                # Gated on the REAL owner check, never the simulated one, so
                # Ashok can always flip this switch even while testing as a
                # guest — see _toggle_role_switch.
                reply = self._toggle_role_switch(chat_id, command)
            elif self._effective_is_owner(chat_id):
                try:
                    reply = self._owner_command_reply(
                        chat_id,
                        command,
                        arg,
                        update_id=update_id,
                    )
                except Exception:
                    LOG.exception('owner command failed chat=%s command=%s', chat_id, command)
                    reply = 'That VIGIL command could not reach live tower data. Try again shortly.'
            else:
                reply = 'JobMaster can help you find verified jobs. Ask naturally in any sentence.'
            if update_id is not None and self.sessions.load_update_reply(update_id) is None:
                self.sessions.save_update_reply(update_id, reply)
            self.api.send(chat_id, reply)
            if self.health_enabled:
                self._write_health(
                    status='running',
                    last_result='ok',
                    last_chat=chat_id,
                    last_kind='owner_command' if self._effective_is_owner(chat_id) else 'restricted_command',
                    last_text=f'/{command}',
                )
            return
        is_reset = bool(RESET_RE.match(clean))
        if clean.lower() == '/start':
            # /start is an explicit "let's begin" — always launches the
            # primary button-driven flow, overwriting any stale state.
            button_reply = self.button_flow.start(chat_id)
            self._send_button_reply(chat_id, button_reply, update_id=update_id)
            return
        if clean.lower() in {'/help', 'help'}:
            reply = self.voice.speak(
                'JobMaster provides verified jobs and live job-market insights. '
                'Ask naturally in any sentence.'
            )
            if update_id is not None:
                self.sessions.save_update_reply(update_id, reply)
            self.api.send(chat_id, reply)
            return
        if is_reset:
            # Guide guests straight back into the primary button path after
            # a reset, instead of leaving them at a bare confirmation line.
            engine_reply = self.engine.handle(clean, chat_id)
            button_reply = self.button_flow.start(chat_id)
            combined = ButtonReply(f'{engine_reply}\n\n{button_reply.text}', button_reply.keyboard)
            self._send_button_reply(chat_id, combined, update_id=update_id)
            self._last_request.pop(chat_id, None)
            return
        onboarding_state = self.sessions.load_onboarding(chat_id)
        old_style_onboarding_active = (
            onboarding_state is not None
            and not str(onboarding_state.get('stage') or '').startswith('btn_')
        )
        if not old_style_onboarding_active and GREETING_RE.match(clean):
            # A bare greeting from a chat with no in-progress LEGACY text
            # onboarding launches the new button-driven flow instead of the
            # old text prompt — see app/telegram_buttons.py.
            button_reply = self.button_flow.start(chat_id)
            self._send_button_reply(chat_id, button_reply, update_id=update_id)
            return
        waitlist_reply = self.button_flow.handle_text(chat_id, clean)
        if waitlist_reply is not None:
            # Only ever True while a guest is mid waitlist-email capture —
            # an integral part of the button flow, not a "give up" case.
            self._send_button_reply(chat_id, waitlist_reply, update_id=update_id)
            return
        now = time.monotonic()
        last = self._last_request.get(chat_id, 0.0)
        if now - last < 1.0:
            reply = 'One request at a time.'
            if update_id is not None:
                self.sessions.save_update_reply(update_id, reply)
            self.api.send(chat_id, reply)
            return
        if not acked:
            self.api.send(chat_id, 'Thinking…')
        engine_ok = True
        try:
            try:
                reply = self.engine.handle(clean, chat_id, update_id=update_id)
            except TypeError as exc:
                if 'update_id' not in str(exc):
                    raise
                # Test doubles and legacy capability adapters may not yet
                # expose the atomic outbox keyword.
                reply = self.engine.handle(clean, chat_id)
        except Exception:
            LOG.exception('request failed chat=%s text=%r', chat_id, clean[:120])
            reply = 'JobMaster could not reach live Watch Tower data. Try again shortly.'
            engine_ok = False
        if engine_ok:
            # Warmth pass only on a real grounded reply — never risk an extra
            # model call on the already-degraded error path. Fact-locked: see
            # app/telegram_voice.py.
            reply = self.voice.speak(reply)
        if update_id is not None and self.sessions.load_update_reply(update_id) is None:
            self.sessions.save_update_reply(update_id, reply)
        self.api.send(chat_id, reply)
        self._last_request[chat_id] = time.monotonic()
        if MORE_RE.match(clean):
            self._page_count += 1
        else:
            self._query_count += 1
        if self.health_enabled:
            self._write_health(
                status='running',
                last_result='ok',
                last_chat=chat_id,
                last_kind='more' if MORE_RE.match(clean) else 'message',
                last_text=clean[:120],
                query_count=self._query_count,
                page_count=self._page_count,
            )

    @staticmethod
    def _normalize_update(update: dict) -> tuple[bool, dict, dict, str | None, str | None]:
        """Fold a raw Telegram update (a `message` or a `callback_query`,
        see `allowed_updates` in `TelegramAPI.updates`) into one common
        shape the poll loop can dispatch uniformly. A button tap is
        re-encoded as BTN_PREFIX-tagged text so it flows through the exact
        same durable per-chat queue as typed messages (see queue_update) —
        callers never need a second code path for it."""
        callback = update.get('callback_query')
        if callback:
            message = callback.get('message') or {}
            chat = message.get('chat') or {}
            sender = callback.get('from') or {}
            data = callback.get('data')
            text = f'{BTN_PREFIX}{data}' if isinstance(data, str) else None
            return True, chat, sender, text, callback.get('id')
        message = update.get('message') or {}
        chat = message.get('chat') or {}
        sender = message.get('from') or {}
        text = message.get('text')
        return False, chat, sender, text, None

    def run(self) -> int:
        self.api.call('deleteWebhook', {'drop_pending_updates': 'false'})
        me = self.api.call('getMe').get('result') or {}
        LOG.info('JobMaster Telegram started bot=@%s', me.get('username', 'unknown'))
        owner_commands_ready = self._configure_command_menu()
        offset_raw = self.sessions.get_state('telegram_update_offset', '')
        if offset_raw.isdigit():
            offset = int(offset_raw)
        else:
            # First dedicated start consumes the Bot API queue normally. Hermes
            # was stopped first, so messages arriving during cutover must not
            # be drained or silently lost.
            offset = 0
            self.sessions.set_state('telegram_update_offset', offset)
        poll_successes = 0
        self._write_health(
            status='starting',
            bot=me.get('username', ''),
            poll_successes=poll_successes,
            owner_commands_ready=owner_commands_ready,
        )

        backoff = 1
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix='jobmaster') as workers:
            # Replay durable updates in Telegram order before opening a new poll.
            # Owner access changes therefore take effect before any later guest
            # message is authorized after a restart.
            for update_id, chat_id, username, text in self.sessions.pending_updates():
                if not self._process_queued(
                    update_id,
                    chat_id,
                    username,
                    text,
                ):
                    self._enqueue_update(
                        workers,
                        update_id,
                        chat_id,
                        username,
                        text,
                    )
            while not STOP:
                try:
                    poll_timeout = 2 if poll_successes < 2 else 25
                    updates = self.api.updates(offset, timeout=poll_timeout)
                    poll_successes += 1
                    backoff = 1
                    self._write_health(
                        status='running' if poll_successes >= 2 else 'starting',
                        bot=me.get('username', ''),
                        poll_successes=poll_successes,
                        last_poll_at=time.time(),
                        owner_commands_ready=owner_commands_ready,
                        error=None,
                    )
                    for update in updates:
                        update_id = int(update.get('update_id', -1))
                        offset = max(offset, update_id + 1)
                        is_callback, chat, sender, text, callback_id = self._normalize_update(update)
                        if chat.get('type') == 'private' and chat.get('id'):
                            if isinstance(text, str):
                                chat_id = str(chat['id'])
                                username = str(sender.get('username') or '')
                                if not self._sender_allowed(chat_id, username):
                                    LOG.info(
                                        'ignored blocked Telegram %s chat=%s username=%s',
                                        'callback' if is_callback else 'sender',
                                        chat_id,
                                        username or 'none',
                                    )
                                    self.sessions.set_state(
                                        'telegram_update_offset',
                                        offset,
                                    )
                                    continue
                                if is_callback and callback_id:
                                    # Best practice: acknowledge the tap (clears
                                    # the button's loading spinner) as soon as
                                    # it is authorized — processing itself may
                                    # take longer via the durable queue below.
                                    self.api.answer_callback(callback_id)
                                if not self._is_owner(chat_id):
                                    observe_identity(chat_id, username)
                                if self.sessions.queue_update(
                                    update_id,
                                    chat_id,
                                    text,
                                    username=username,
                                ):
                                    parsed = self._command(text)
                                    if (
                                        self._is_owner(chat_id)
                                        and parsed
                                        and parsed[0] in OWNER_MANAGEMENT_COMMANDS
                                    ):
                                        # Access changes are a barrier in the
                                        # global Telegram update order. Apply
                                        # them before authorizing a later
                                        # message from another chat.
                                        if not self._process_queued(
                                            update_id,
                                            chat_id,
                                            username,
                                            text,
                                        ):
                                            self._enqueue_update(
                                                workers,
                                                update_id,
                                                chat_id,
                                                username,
                                                text,
                                            )
                                        self.sessions.set_state(
                                            'telegram_update_offset',
                                            offset,
                                        )
                                        continue
                                    acked = self._pre_ack(chat_id, text)
                                    self._enqueue_update(
                                        workers,
                                        update_id,
                                        chat_id,
                                        username,
                                        text,
                                        acked=acked,
                                    )
                        # Offset advances only after an accepted private message
                        # is durable in SQLite (or for an intentionally ignored
                        # update). A process crash cannot silently lose it.
                        self.sessions.set_state('telegram_update_offset', offset)
                except urllib.error.HTTPError as exc:
                    body = exc.read().decode(errors='replace')
                    if exc.code == 409:
                        LOG.error('Telegram poll conflict: another consumer owns getUpdates: %s', body[:300])
                        self._write_health(status='conflict', error='another Telegram poller is active')
                        return 9
                    LOG.warning('Telegram HTTP %s: %s', exc.code, body[:300])
                    self._write_health(status='degraded', error=f'HTTP {exc.code}')
                except Exception as exc:
                    LOG.exception('Telegram poll failed')
                    self._write_health(status='degraded', error=str(exc)[:200])
                if not STOP:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
        self._write_health(status='stopped')
        return 0

    @staticmethod
    def _write_health(**fields: Any) -> None:
        with HEALTH_LOCK:
            HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
            current: dict[str, Any] = {}
            if HEALTH_FILE.exists():
                try:
                    current = json.loads(HEALTH_FILE.read_text(encoding='utf-8'))
                except (OSError, json.JSONDecodeError):
                    current = {}
            current.update(fields)
            current['pid'] = os.getpid()
            current['version'] = VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else 'unknown'
            current['updated_at'] = time.time()
            tmp = HEALTH_FILE.with_suffix('.tmp')
            tmp.write_text(json.dumps(current, indent=2), encoding='utf-8')
            tmp.replace(HEALTH_FILE)


def _stop(_signum, _frame) -> None:
    global STOP
    STOP = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='JobMaster Telegram service')
    parser.add_argument('command', nargs='?', default='run', choices=['run', 'smoke'])
    parser.add_argument('--chat', default='')
    parser.add_argument('--query', default='Fresh jobs in Bangalore in AI space for fresher')
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )
    env = load_env()
    api = TelegramAPI(env.get('TELEGRAM_BOT_TOKEN', ''))
    owner_chat = (env.get('TELEGRAM_HOME_CHANNEL') or '').strip()
    bot = JobMasterTelegramBot(
        api,
        health_enabled=args.command != 'smoke',
        owner_chat_ids={owner_chat} if owner_chat else set(),
    )
    if args.command == 'smoke':
        if not args.chat:
            parser.error('smoke requires --chat')
        try:
            bot.smoke(args.chat, args.query)
            return 0
        except Exception:
            LOG.exception('production smoke failed')
            return 8
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    return bot.run()


if __name__ == '__main__':
    raise SystemExit(main())
