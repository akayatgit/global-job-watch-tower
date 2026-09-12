#!/usr/bin/env python3
"""Telegram ingress for Prompt Tower.

Every user gets /igtovid · /pintovid. No JobMaster, LinkedIn, or jobseeker
copy is sent — Ashok 2026-09-12.
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
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import telegram_alerts, telegram_broadcast  # noqa: E402
from app.cities import city_label  # noqa: E402
from app.telegram_buttons import BTN_PREFIX, EXPERIENCE_LABELS, ButtonFlow, ButtonReply  # noqa: E402
from app.telegram_job_search import (  # noqa: E402
    GREETING_RE,
    MORE_RE,
    PAGE_SIZE,
    RESET_RE,
    ROLE_FAMILY_LABELS,
    JobMasterEngine,
    _http_get as _http_get_default,
    _http_post,
    parse_window_token,
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
from app.telegram_prompts import (  # noqa: E402
    CALLBACK_PREFIX as PROMPT_CALLBACK_PREFIX,
    REVERSE_ASK,
    STATE_PHOTO as PROMPT_PHOTO_STATE,
    STATE_VIDEO as PROMPT_VIDEO_STATE,
    PromptDeck,
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
    'health': 'health',
}
OWNER_QUERY_COMMANDS: dict[str, Any] = {}
OWNER_COMPANY_COMMANDS = frozenset()
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
    'checkaccess',
    'push',
    'pushconfirm',
    'pushcancel',
    'pushstats',
    'resetdata',
    'resetconfirm',
    'resetcancel',
    'prompts',
    'promptscan',
    'addprompt',
    'promptstats',
    'promptperf',
    'igtovid',
    'pintovid',
    'pintovideo',
    'reverseprompt',
})
# Daily-deck taps stay owner-only. Reverse taps (model / twist / cancel /
# photo / video) are public — Ashok 2026-09-12.
OWNER_DECK_ACTIONS = frozenset({
    'list', 'scan', 'stats', 'sel', 'img', 'go', 'rate', 'posted',
})
# Heavy prompt-tower commands (Ollama / scan). Reverse intake is instant
# and must NOT wait on this queue — Ashok (2026-09-11): /igtovid was slow.
PROMPT_COMMANDS = frozenset({
    'prompts', 'promptscan', 'addprompt', 'promptstats', 'promptperf',
})
REVERSE_INTAKE_COMMANDS = frozenset({
    'igtovid', 'pintovid', 'pintovideo', 'reverseprompt',
})
# Synthetic tap the poll loop queues when the OWNER sends a photo with no
# caption — the durable inbox is text-only, and the prompt flow needs the
# photo itself to be an event ("here is the product image").
PROMPT_PHOTO_TAP = f'{BTN_PREFIX}{PROMPT_CALLBACK_PREFIX}photo'
# Same shape for a forwarded video (the reverse-prompt source clip).
PROMPT_VIDEO_TAP = f'{BTN_PREFIX}{PROMPT_CALLBACK_PREFIX}video'
PROMPT_DAILY_CHECK_S = 600  # bot-side check for a fresh daily shortlist
# 10 minutes to review a staged /push before it expires unconfirmed —
# short enough that a forgotten broadcast never fires hours later.
PENDING_PUSH_TTL_S = 600
# Same review window for a staged /resetdata — a destructive action must
# never fire from a stale confirmation.
PENDING_RESET_TTL_S = 600
# /topfreshers — video-gem mining. Filters are key:value tokens; a value
# runs until the next key or the trailing experience number, so multi-word
# companies ("company:Tata Consultancy Services 0") parse whole. city: and
# time: added 2026-08-18; trailing 0 is optional (defaults to fresher gems).
TOPFRESHERS_FILTER_RE = re.compile(
    r'(company|skill|role|city|time)\s*:\s*(.+?)(?=\s+(?:company|skill|role|city|time)\s*:|\s+\d+\s*$|\s*$)',
    re.IGNORECASE,
)
TOPFRESHERS_LEVEL_RE = re.compile(r'(?:^|\s)(\d+)\s*$')
TOPFRESHERS_PAGE_SIZE = 10
TOPFRESHERS_API_FETCH = 40  # fetch ahead so we can detect "has more"
TOPFRESHERS_USAGE = (
    'Usage: /topfreshers [company:<name>] [skill:<term>] '
    '[role:<term>] [city:<chennai/bangalore/remote>] [time:<24hrs>] [0]\n'
    'Examples: /topfreshers 0 · /topfreshers skill:data_analyst '
    'city:chennai/bangalore/remote time:24hrs · '
    '/topfreshers company:Deloitte 0'
)
TOPFRESHERS_TIME_RE = re.compile(
    r'^(?:'
    r'(?P<h24>24\s*h(?:rs?|ours?)?)|'
    r'(?P<d>(?P<days>\d+)\s*d(?:ays?)?)|'
    r'(?P<n>\d+)'
    r')$',
    re.IGNORECASE,
)
# Ashok-only self-test toggle: no second phone needed to see the guest
# experience. Always dispatched off the REAL owner check (never the
# simulated one) so this pair of commands can never lock him out of his
# own chat — see _toggle_role_switch.
OWNER_ROLE_SWITCH_COMMANDS = frozenset({'actasguest', 'actasowner'})
OWNER_COMMANDS = frozenset((
    *OWNER_BOARD_COMMANDS,
    *OWNER_QUERY_COMMANDS,
    *OWNER_COMPANY_COMMANDS,
    *OWNER_MANAGEMENT_COMMANDS,
    *OWNER_ROLE_SWITCH_COMMANDS,
))
PUBLIC_MENU = [
    {'command': 'igtovid', 'description': 'Reverse an Instagram reel into a prompt'},
    {'command': 'pintovid', 'description': 'Reverse a Pinterest pin into a prompt'},
    {'command': 'help', 'description': 'How Prompt Tower works'},
]
OWNER_MENU = [
    {'command': 'prompts', 'description': "Today's top-10 video prompts (tap to open)"},
    {'command': 'promptscan', 'description': 'Collect + score prompts now'},
    {'command': 'addprompt', 'description': 'Add a prompt you found'},
    {'command': 'promptperf', 'description': 'Teach the ranker: likes/comments/saves'},
    {'command': 'promptstats', 'description': 'Prompt Tower numbers'},
    {'command': 'igtovid', 'description': 'Reverse prompt from an Instagram reel'},
    {'command': 'pintovid', 'description': 'Reverse prompt from a Pinterest pin'},
    {'command': 'help', 'description': 'All commands with options'},
    {'command': 'allowguest', 'description': 'Un-block / VIP a person'},
    {'command': 'blockguest', 'description': 'Block a person (public by default)'},
    {'command': 'guests', 'description': 'Access dashboard'},
    {'command': 'history', 'description': 'User conversation history'},
    {'command': 'checkaccess', 'description': "Why can/can't a person text?"},
    {'command': 'push', 'description': 'Stage a broadcast (text/photo)'},
    {'command': 'pushconfirm', 'description': 'Send the staged broadcast'},
    {'command': 'pushcancel', 'description': 'Discard the staged broadcast'},
    {'command': 'pushstats', 'description': 'Last broadcast reach + likes'},
    {'command': 'actasguest', 'description': 'Test this chat as a user'},
    {'command': 'actasowner', 'description': 'Back to owner mode'},
    {'command': 'health', 'description': 'Tower health'},
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


def _inline_keyboard_button(label: str, data: str) -> dict[str, str]:
    """http(s) → URL button (Save file). Everything else is a callback tap."""
    if str(data).startswith(('http://', 'https://')):
        return {'text': label, 'url': data}
    return {'text': label, 'callback_data': data}


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
                    [_inline_keyboard_button(label, data) for label, data in row]
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

    def send_photo(
        self,
        chat_id: str,
        photo_file_id: str,
        caption: str = '',
        keyboard: list[list[tuple[str, str]]] | None = None,
    ) -> None:
        """Broadcast image (+optional caption/keyboard). Telegram captions
        cap at 1024 UTF-16 units — longer text ships as a separate message
        (with the keyboard) right after the photo instead of truncating."""
        text = (caption or '').strip()
        markup = None
        if keyboard:
            markup = json.dumps({
                'inline_keyboard': [
                    [_inline_keyboard_button(label, data) for label, data in row]
                    for row in keyboard
                ]
            })
        if text and _utf16_units(text) <= 1024:
            payload: dict[str, Any] = {'chat_id': str(chat_id), 'photo': photo_file_id, 'caption': text}
            if markup is not None:
                payload['reply_markup'] = markup
            self.call('sendPhoto', payload)
            return
        self.call('sendPhoto', {'chat_id': str(chat_id), 'photo': photo_file_id})
        if text:
            self.send_keyboard(chat_id, text, keyboard)

    def _multipart(self, method: str, fields: dict[str, str], file_field: str, filename: str, data: bytes, content_type: str, timeout: int = 300) -> dict:
        """multipart/form-data upload (sendPhoto/sendVideo with real bytes —
        the tower sits behind Cloudflare Access, so Telegram cannot fetch
        our asset URLs itself)."""
        boundary = f'----PromptTower{uuid.uuid4().hex}'
        body = bytearray()
        for key, value in fields.items():
            body += (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
            ).encode('utf-8')
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
            f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'
        ).encode('utf-8')
        body += data
        body += f'\r\n--{boundary}--\r\n'.encode('utf-8')
        req = urllib.request.Request(
            f'{self.base}/{method}',
            data=bytes(body),
            headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        if not payload.get('ok'):
            raise RuntimeError(f'Telegram {method} failed: {payload.get("description", "unknown")}')
        return payload

    def send_photo_bytes(self, chat_id: str, data: bytes, caption: str = '') -> None:
        fields = {'chat_id': str(chat_id)}
        if caption:
            fields['caption'] = _truncate_utf16(caption, 1024)
        self._multipart('sendPhoto', fields, 'photo', 'card.png', data, 'image/png')

    def send_video_bytes(self, chat_id: str, data: bytes, caption: str = '') -> None:
        fields = {'chat_id': str(chat_id), 'supports_streaming': 'true'}
        if caption:
            fields['caption'] = _truncate_utf16(caption, 1024)
        self._multipart('sendVideo', fields, 'video', 'prompt.mp4', data, 'video/mp4', timeout=600)

    def send_document_bytes(
        self, chat_id: str, data: bytes, filename: str = 'frame.jpg', caption: str = '',
    ) -> None:
        """sendDocument keeps the original JPEG so Ashok can download and attach it."""
        name = (filename or 'frame.jpg').replace('/', '-')
        fields = {'chat_id': str(chat_id)}
        if caption:
            fields['caption'] = _truncate_utf16(caption, 1024)
        self._multipart('sendDocument', fields, 'document', name, data, 'image/jpeg')

    def get_file_bytes(self, file_id: str) -> tuple[bytes, str]:
        """Download a photo or video the owner sent (Bot API getFile → file path).
        Videos use a longer timeout; Telegram's bot-download ceiling is 20 MB
        — larger clips must arrive as a link, not a forwarded file."""
        info = self.call('getFile', {'file_id': file_id}).get('result') or {}
        path = str(info.get('file_path') or '')
        if not path:
            raise RuntimeError('Telegram getFile returned no file_path')
        token = self.base.rsplit('/bot', 1)[1]
        url = f'https://api.telegram.org/file/bot{token}/{path}'
        lower = path.lower()
        is_video = lower.endswith(('.mp4', '.mov', '.m4v', '.webm', '.mkv'))
        with urllib.request.urlopen(url, timeout=180 if is_video else 120) as resp:
            data = resp.read()
        if is_video:
            content_type = 'video/webm' if lower.endswith('.webm') else 'video/mp4'
        elif lower.endswith('.png'):
            content_type = 'image/png'
        else:
            content_type = 'image/jpeg'
        return data, content_type

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
        tower_post=None,
    ):
        self.api = api
        self.sessions = sessions or TelegramSessionStore()
        self.engine = engine or JobMasterEngine(sessions=self.sessions)
        # JSON POST to the tower API (watchlist add, data reset) —
        # injectable for tests, same base URL as the engine's reads.
        self.tower_post = tower_post or _http_post
        self.voice = voice or VoiceLayer()
        self.button_flow = ButtonFlow(self.engine, self.sessions)
        self.health_enabled = health_enabled
        self.owner_chat_ids = {str(chat_id) for chat_id in (owner_chat_ids or set())}
        self.board_renderer = board_renderer or render_board
        # Prompt Tower deck (2026-09-09): owner-only, tower API only. Asset
        # bytes come from the LOCAL tower (127.0.0.1) and are uploaded to
        # Telegram as multipart — Telegram can't pass Cloudflare Access.
        self.deck = PromptDeck(
            self.sessions,
            api_get=getattr(self.engine, 'api_get', None) or _http_get_default,
            api_post=self.tower_post,
            download_photo=getattr(self.api, 'get_file_bytes', None),
            fetch_asset=self._fetch_local_asset,
            send_photo_bytes=getattr(self.api, 'send_photo_bytes', None),
            send_video_bytes=getattr(self.api, 'send_video_bytes', None),
            send_document_bytes=getattr(self.api, 'send_document_bytes', None),
            send_text=self.api.send,
            on_render_started=self._start_render_watch,
            on_reverse_started=self._start_reverse_watch,
            on_twist_started=self._start_twist_watch,
            send_keyboard=self.api.send_keyboard,
        )
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
    def _fetch_local_asset(key: str) -> bytes:
        """Rendered card / video bytes straight from the local tower."""
        from app.telegram_job_search import BASE as TOWER_BASE

        url = f'{TOWER_BASE}/api/partner/v1/assets/{urllib.parse.quote(key)}'
        with urllib.request.urlopen(url, timeout=300) as resp:
            return resp.read()

    def _start_render_watch(self, chat_id: str, render_id: int) -> None:
        """Background watcher: polls the render row, uploads card + video."""
        thread = threading.Thread(
            target=self._watch_render_safely,
            args=(chat_id, render_id),
            daemon=True,
            name=f'prompt-render-{render_id}',
        )
        thread.start()

    def _watch_render_safely(self, chat_id: str, render_id: int) -> None:
        try:
            self.deck.watch_render(chat_id, render_id)
        except Exception:
            LOG.exception('render watch crashed render=%s', render_id)

    def _start_reverse_watch(self, chat_id: str, reverse_id: int) -> None:
        """Background watcher: polls the reverse-prompt row, uploads reel + text."""
        thread = threading.Thread(
            target=self._watch_reverse_safely,
            args=(chat_id, reverse_id),
            daemon=True,
            name=f'prompt-reverse-{reverse_id}',
        )
        thread.start()

    def _watch_reverse_safely(self, chat_id: str, reverse_id: int) -> None:
        try:
            self.deck.watch_reverse(chat_id, reverse_id)
        except Exception:
            LOG.exception('reverse watch crashed reverse=%s', reverse_id)

    def _start_twist_watch(self, chat_id: str, reverse_id: int) -> None:
        thread = threading.Thread(
            target=self._watch_twist_safely,
            args=(chat_id, reverse_id),
            daemon=True,
            name=f'prompt-twist-{reverse_id}',
        )
        thread.start()

    def _watch_twist_safely(self, chat_id: str, reverse_id: int) -> None:
        try:
            self.deck.watch_twist(chat_id, reverse_id)
        except Exception:
            LOG.exception('twist watch crashed reverse=%s', reverse_id)

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
                self.api.call('setMyCommands', {
                    'scope': json.dumps({'type': 'chat', 'chat_id': scope_chat_id}),
                    'commands': json.dumps(PUBLIC_MENU),
                })
            except Exception:
                LOG.exception(
                    'failed to show public command menu for user simulation chat=%s', chat_id,
                )
            return (
                'Testing mode ON. This chat now behaves like any user: '
                '/igtovid · /pintovid work, ops commands do not. '
                'Send /actasowner anytime to switch back.'
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
    ) -> str | ButtonReply:
        if command == 'help':
            return self._owner_help()
        if command in OWNER_MANAGEMENT_COMMANDS:
            return self._management_reply(chat_id, command, arg)
        if command in OWNER_BOARD_COMMANDS:
            tokens = (arg or '').split()
            unfiltered = any(t.lower().lstrip('-–—') == 'unfiltered' for t in tokens)
            tokens = [t for t in tokens if t.lower().lstrip('-–—') != 'unfiltered']
            days = None
            if tokens:
                try:
                    days = int(tokens[0])
                except ValueError:
                    days = None
            if unfiltered:
                return self.board_renderer(
                    OWNER_BOARD_COMMANDS[command], days=days, unfiltered=True,
                )
            return self.board_renderer(OWNER_BOARD_COMMANDS[command], days=days)
        return REVERSE_ASK

    def _companyjobs_reply(
        self,
        chat_id: str,
        arg: str,
        *,
        update_id: int | None,
    ) -> str:
        """/companyjobs <company> [24h | 7 | 30] — a trailing window token is
        optional; everything before it is the company name (default 7 days)."""
        tokens = (arg or '').split()
        unfiltered = any(t.lower().lstrip('-–—') == 'unfiltered' for t in tokens)
        tokens = [t for t in tokens if t.lower().lstrip('-–—') != 'unfiltered']
        usage = (
            'Usage: /companyjobs <company> [24h | 7 | 30]\n'
            'Windows: 24h (caught) · 7 (posted, default) · 30 (this month) — '
            'also today, 1, 2, 4, 14.'
        )
        if not tokens:
            return usage
        days = parse_window_token(tokens[-1]) if len(tokens) >= 2 else None
        if days is not None:
            name = ' '.join(tokens[:-1])
        else:
            days = 7
            name = ' '.join(tokens)
        if unfiltered:
            name = f'{name} -unfiltered'
        try:
            return self.engine.company_jobs(name, days, chat_id, update_id=update_id)
        except TypeError as exc:
            if 'update_id' not in str(exc):
                raise
            return self.engine.company_jobs(name, days, chat_id)

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

    def _management_reply(self, chat_id: str, command: str, arg: str) -> str | ButtonReply:
        allow_commands = {'allowguest', 'allow', 'allowuser'}
        block_commands = {'blockguest', 'block', 'revoke', 'revokeuser'}
        if command in PROMPT_COMMANDS or command in REVERSE_INTAKE_COMMANDS:
            return self.deck.handle_command(chat_id, command, arg)
        if command == 'push':
            return self._stage_push(chat_id, arg)
        if command == 'pushcancel':
            self._clear_pending_push(chat_id)
            return 'Discarded the pending push.'
        if command == 'pushconfirm':
            return self._confirm_push(chat_id)
        if command == 'pushstats':
            return self._push_stats()
        if command == 'topfreshers':
            return self._topfreshers_reply(chat_id, arg)
        if command == 'funnel':
            return self._funnel_reply(arg)
        if command == 'addcompany':
            return self._add_company_reply(arg)
        if command == 'companies':
            return self._companies_reply()
        if command == 'resetdata':
            return self._stage_reset(chat_id)
        if command == 'resetconfirm':
            return self._confirm_reset(chat_id)
        if command == 'resetcancel':
            self.sessions.set_state(f'pending_reset_at:{chat_id}', '')
            return 'Reset cancelled — nothing was wiped.'
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

    def _clear_pending_push(self, owner_chat_id: str) -> None:
        for suffix in ('text', 'photo', 'at'):
            self.sessions.set_state(f'pending_push_{suffix}:{owner_chat_id}', '')

    def _stage_push(self, owner_chat_id: str, arg: str) -> str:
        text = (arg or '').strip()
        photo_file_id = self.sessions.get_state(f'pending_push_photo:{owner_chat_id}', '')
        if not text and not photo_file_id:
            return (
                'Usage: /push <message> — or send a photo with caption '
                '"/push <message>" for an image broadcast.'
            )
        self.sessions.set_state(f'pending_push_text:{owner_chat_id}', text)
        self.sessions.set_state(f'pending_push_at:{owner_chat_id}', time.time())
        count = self.sessions.count_active_broadcast_subscribers()
        kind = 'text + photo' if (text and photo_file_id) else ('photo' if photo_file_id else 'text')
        preview = text or '(no caption)'
        return (
            f'READY TO SEND ({kind}) to {count} subscriber(s):\n\n{preview}\n\n'
            'Reply /pushconfirm within 10 minutes to send, or /pushcancel to discard.'
        )

    def _confirm_push(self, owner_chat_id: str) -> str:
        at_raw = self.sessions.get_state(f'pending_push_at:{owner_chat_id}', '')
        if not at_raw:
            return 'No pending push. Start with /push <message>.'
        try:
            staged_at = float(at_raw)
        except ValueError:
            staged_at = 0.0
        if time.time() - staged_at > PENDING_PUSH_TTL_S:
            self._clear_pending_push(owner_chat_id)
            return 'That pending push expired after 10 minutes. Start again with /push <message>.'
        text = self.sessions.get_state(f'pending_push_text:{owner_chat_id}', '')
        photo_file_id = self.sessions.get_state(f'pending_push_photo:{owner_chat_id}', '')
        self._clear_pending_push(owner_chat_id)

        def _send(target_chat_id: str, message_text: str, image_id: str, keyboard) -> None:
            if image_id:
                self.api.send_photo(target_chat_id, image_id, message_text, keyboard)
            else:
                self.api.send_keyboard(target_chat_id, message_text, keyboard)

        result = telegram_broadcast.send_broadcast(
            self.sessions, _send, text=text, photo_file_id=photo_file_id,
        )
        tail = f", {result['failed']} failed" if result['failed'] else ''
        return f"Sent to {result['sent']}/{result['total']} subscriber(s){tail}."

    @staticmethod
    def _ago(iso: str | None) -> str:
        """Relative time for roster rows ('2h ago'), per the timestamp law."""
        from datetime import datetime, timezone
        if not iso:
            return 'never'
        try:
            stamp = datetime.fromisoformat(str(iso))
        except ValueError:
            return 'never'
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        seconds = max(0, int((datetime.now(timezone.utc) - stamp).total_seconds()))
        if seconds < 90:
            return 'just now'
        minutes = seconds // 60
        if minutes < 60:
            return f'{minutes}m ago'
        hours = minutes // 60
        if hours < 48:
            return f'{hours}h ago'
        return f'{hours // 24}d ago'

    def _companies_reply(self) -> str:
        """/companies — the full MNC roster, never truncated (long replies
        are already chunked by the send path)."""
        try:
            data = self.engine.api_get('/api/watchlist/companies', None)
        except Exception:
            return 'Tower is unreachable right now — try /companies again in a minute.'
        rows = data.get('companies') if isinstance(data, dict) else None
        if not rows:
            return (
                'No companies on the watchlist yet — add the first giant '
                'with /addcompany <name>.'
            )
        on = sum(1 for row in rows if row.get('enabled'))
        paused = len(rows) - on
        header = f'MNC WATCHLIST · {len(rows)} companies · {on} on'
        if paused:
            header += f' · {paused} paused'
        lines = [header, '']
        for i, row in enumerate(rows, 1):
            state = '' if row.get('enabled') else ' · paused'
            lines.append(
                f"{i}. {row.get('company')} — {row.get('jobs_total', 0)} jobs "
                f"({row.get('jobs_24h', 0)} in 24h) · "
                f"scraped {self._ago(row.get('last_run_at'))}{state}"
            )
        return '\n'.join(lines)

    def _funnel_reply(self, arg: str) -> str:
        """/funnel [hours] — where jobs die between LinkedIn and the bot."""
        tokens = (arg or '').split()
        hours = 24
        if tokens:
            try:
                hours = max(1, min(int(tokens[0]), 720))
            except ValueError:
                return 'Usage: /funnel [hours] — e.g. /funnel or /funnel 48'
        try:
            data = self.engine.api_get('/api/jobs/funnel', {'hours': hours})
        except Exception:
            return 'Tower is unreachable right now — try /funnel again in a minute.'
        if not isinstance(data, dict):
            data = {}
        last = data.get('last_catch_at')
        last_line = f'Last catch: {last}' if last else 'Last catch: never'
        return '\n'.join([
            f'🔬 JOB FUNNEL · last {data.get("hours", hours)}h',
            '',
            f'Caught: {data.get("caught", 0)}',
            f'└ in Chennai/Bengaluru/Remote: {data.get("in_collection_cities", 0)}',
            f'└ GTM role titles: {data.get("role_matched", 0)}',
            f'└ detail-verified: {data.get("detail_verified", 0)}',
            f'└ servable fresher gems: {data.get("servable_fresher", 0)}',
            '',
            f'Pending verification: {data.get("pending_verification", 0)}',
            f'All-time stored: {data.get("total_all_time", 0)}',
            f'Enabled searches: {data.get("enabled_searches", 0)} · '
            f'runs in window: {data.get("runs_in_window", 0)}',
            last_line,
        ])

    @staticmethod
    def _parse_topfreshers_time(raw: str | None) -> int | None:
        """Map time: tokens to /api/jobs days window. 24hrs → 0 (rolling 24h)."""
        if not raw:
            return None
        text = raw.strip().lower().replace('_', '')
        match = TOPFRESHERS_TIME_RE.match(text)
        if not match:
            return None
        if match.group('h24'):
            return 0
        if match.group('days') is not None:
            days = int(match.group('days'))
        else:
            days = int(match.group('n'))
        if days == 24:
            # Bare "24" means hours, same as 24hrs — not 24 calendar days.
            return 0
        if days in (0, 1, 2, 4, 7, 14, 30):
            return days
        return None

    def _topfreshers_reply(self, chat_id: str, arg: str) -> str | ButtonReply:
        """/topfreshers — video gems, 10 at a time, More until the end."""
        text = (arg or '').strip()
        filters = {
            m.group(1).lower(): m.group(2).strip()
            for m in TOPFRESHERS_FILTER_RE.finditer(text)
            if m.group(2).strip()
        }
        level_match = TOPFRESHERS_LEVEL_RE.search(text)
        level = int(level_match.group(1)) if level_match else 0
        if level != 0:
            return (
                'Only 0 is supported — /topfreshers lists jobs that '
                'explicitly say fresher or 0 experience.\n' + TOPFRESHERS_USAGE
            )
        days = self._parse_topfreshers_time(filters.get('time'))
        if filters.get('time') and days is None:
            return (
                'time: must be 24hrs (or 1 / 2 / 4 / 7 / 14 / 30).\n'
                + TOPFRESHERS_USAGE
            )
        intent = {
            'kind': 'topfreshers',
            'company': filters.get('company') or '',
            'skill': filters.get('skill') or '',
            'role': filters.get('role') or '',
            'city': filters.get('city') or '',
            'days': days,
        }
        return self._topfreshers_page(chat_id, intent, seen_ids=[], page=0)

    def _topfreshers_page(
        self,
        chat_id: str,
        intent: dict[str, Any],
        *,
        seen_ids: list[str],
        page: int,
    ) -> str | ButtonReply:
        params: dict[str, Any] = {
            'limit': TOPFRESHERS_API_FETCH,
            'verified': 1,
            'explicit_fresher': 1,
        }
        if intent.get('company'):
            params['company'] = intent['company']
        if intent.get('skill'):
            params['skill'] = intent['skill']
        if intent.get('city'):
            params['city'] = intent['city']
        if intent.get('days') is not None:
            params['days'] = intent['days']
        role = (intent.get('role') or '').strip()
        if role:
            if role.lower() in ROLE_FAMILY_LABELS:
                params['role_family'] = role.lower()
            else:
                params['title_terms'] = role

        prior = set(seen_ids)
        collected: list[dict[str, Any]] = []
        new_ids: list[str] = []
        offset = 0
        has_more = False
        try:
            while len(collected) <= TOPFRESHERS_PAGE_SIZE and offset < 2000:
                batch = self.engine.api_get(
                    '/api/jobs', {**params, 'offset': offset},
                )
                if not isinstance(batch, list):
                    batch = []
                if not batch:
                    break
                for job in batch:
                    key = str(
                        job.get('linkedin_job_id')
                        or job.get('job_url')
                        or job.get('id')
                        or ''
                    )
                    if not key or key in prior:
                        continue
                    prior.add(key)
                    if len(collected) < TOPFRESHERS_PAGE_SIZE:
                        collected.append(job)
                        new_ids.append(key)
                    else:
                        has_more = True
                        break
                if has_more or len(batch) < params['limit']:
                    break
                offset += len(batch)
        except Exception:
            return 'Tower is unreachable right now — try /topfreshers again in a minute.'

        applied_bits = []
        for key in ('company', 'skill', 'role', 'city'):
            if intent.get(key):
                applied_bits.append(f'{key}: {intent[key]}')
        if intent.get('days') is not None:
            applied_bits.append(
                'time: 24hrs' if intent['days'] == 0 else f"time: {intent['days']}d"
            )
        applied = ' · '.join(applied_bits)

        if not collected:
            if page > 0:
                body = 'No more fresher gems for these filters.'
                self.sessions.apply_result(
                    chat_id,
                    body,
                    intent=intent,
                    page=page,
                    seen_ids=seen_ids,
                )
                return body
            scope = f' for {applied}' if applied else ''
            funnel_line = ''
            try:
                funnel = self.engine.api_get('/api/jobs/funnel', {'hours': 24})
                if isinstance(funnel, dict):
                    funnel_line = (
                        f'\nFunnel 24h: {funnel.get("caught", 0)} caught · '
                        f'{funnel.get("detail_verified", 0)} verified · '
                        f'{funnel.get("servable_fresher", 0)} servable '
                        f'({funnel.get("pending_verification", 0)} pending check). '
                        'Full picture: /funnel'
                    )
            except Exception:
                pass
            return (
                f'No checked explicit-fresher gems{scope} yet.'
                f'{funnel_line}\n'
                'Verification may still be draining — /health shows the queue. '
                'Widen the filters or check back shortly.\n' + TOPFRESHERS_USAGE
            )

        start = page * TOPFRESHERS_PAGE_SIZE + 1
        lines = [
            f'🎬 TOP FRESHER GEMS · {start}–{start + len(collected) - 1}'
            f'{" · more available" if has_more else " · end"}'
            ' · fresher in title / 0–1 yrs stated'
        ]
        if applied:
            lines.append(f'Filters: {applied}')
        lines.append('')
        for i, job in enumerate(collected, start):
            place = (
                city_label(job.get('city_key')) if job.get('city_key') else None
            ) or job.get('location') or 'India'
            row = (
                f"{i}. {job.get('title') or 'Untitled'} — "
                f"{job.get('company') or 'Unknown company'} — {place}"
            )
            salary = job.get('salary_text')
            if salary:
                row += f' — 💰 {salary}'
            lines.append(row)
            lines.append(str(job.get('job_url') or ''))
        if has_more:
            lines.append('')
            lines.append('Reply more for 10 more gems.')

        body = '\n'.join(lines)
        self.sessions.apply_result(
            chat_id,
            body,
            intent=intent,
            page=page,
            seen_ids=[*seen_ids, *new_ids],
        )
        if has_more:
            return ButtonReply(body, [[('More gems ▸', 'more')]])
        return body

    def _continue_topfreshers(self, chat_id: str) -> str | ButtonReply | None:
        """Paginate a saved /topfreshers session. None = not a gems session."""
        saved = self.sessions.load_search(chat_id)
        if not saved:
            return None
        intent, page, seen_ids = saved
        if (intent or {}).get('kind') != 'topfreshers':
            return None
        return self._topfreshers_page(
            chat_id, intent, seen_ids=list(seen_ids or []), page=page + 1,
        )

    def _owner_help(self) -> str:
        """/help for Ashok — Prompt Tower commands only."""
        lines = [
            'PROMPT TOWER · ALL COMMANDS',
            '',
            'Everyone: /igtovid · /pintovid — send the Instagram or Pinterest link.',
            'Then Whats the hook? → Select a Prompt Model… → Show / Copy / Twist on the finished clip.',
            '',
            'Ops:',
            "/prompts [YYYY-MM-DD] — today's top-10",
            '/promptscan — collect + score now',
            '/addprompt <text> — add a prompt',
            '/promptperf <id> likes=.. comments=.. saves=.. views=..',
            '/promptstats — tower numbers',
            '/history <@username or ID> [1–40]',
            '/checkaccess <@username or ID>',
            '/allowguest <@username or ID> [minutes] · /blockguest <@username or ID>',
            '/push <message> → /pushconfirm within 10 min',
            '/health — tower health',
            '',
            'Everything:',
        ]
        seen: set[str] = set()
        for item in OWNER_MENU:
            if item['command'] in seen:
                continue
            seen.add(item['command'])
            lines.append(f"/{item['command']} — {item['description']}")
        return '\n'.join(lines)

    def _add_company_reply(self, arg: str) -> str:
        """/addcompany <name> — grow the MNC watchlist from the phone."""
        name = (arg or '').strip()
        if not name:
            return (
                'Usage: /addcompany <company name> — e.g. /addcompany Nvidia\n'
                'Adds the company to the MNC watchlist: daily fresher watch '
                '+ first scrape right away.'
            )
        try:
            result = self.tower_post('/api/watchlist/companies', {'name': name})
        except Exception:
            return 'Tower is unreachable right now — try /addcompany again in a minute.'
        display = str(result.get('company') or name)
        if result.get('created'):
            first = (
                'First scrape is queued now'
                if result.get('first_scrape_queued')
                else 'First scrape joins the next free slot'
            )
            return (
                f'✅ {display} added to the MNC watchlist. {first}; '
                'its fresher openings are watched daily from here.'
            )
        return f'👀 {display} is already on the watchlist — daily watch continues.'

    def _stage_reset(self, chat_id: str) -> str:
        """/resetdata — stage the base-level wipe with an honest preview."""
        try:
            preview = self.engine.api_get('/api/tower/reset-preview', None)
        except Exception:
            return 'Tower is unreachable right now — cannot stage a reset.'
        if not isinstance(preview, dict):
            return 'Tower is unreachable right now — cannot stage a reset.'
        self.sessions.set_state(f'pending_reset_at:{chat_id}', time.time())
        active = [str(name) for name in (preview.get('active_searches') or [])]
        if active:
            shown = ', '.join(active[:3]) + ('…' if len(active) > 3 else '')
            disturb = f'Disturbs: {len(active)} live search(es) will be cancelled — {shown}'
        else:
            disturb = 'Disturbs: no search is running right now'
        return (
            '⚠️ TOWER DATA RESET — staged\n\n'
            f"Wipes: {preview.get('jobs', 0)} jobs · "
            f"{preview.get('companies_unwatched_wiped', 0)} unwatched companies · "
            f"{preview.get('runs', 0)} run records\n"
            f"Keeps: every search definition, "
            f"{preview.get('companies_watched_kept', 0)} watched companies, "
            'guests, alerts, chat history\n'
            f'{disturb}\n'
            'After the wipe, every search re-runs automatically one by one.\n\n'
            'Reply /resetconfirm within 10 minutes to execute, or /resetcancel.'
        )

    def _confirm_reset(self, chat_id: str) -> str:
        at_raw = self.sessions.get_state(f'pending_reset_at:{chat_id}', '')
        if not at_raw:
            return 'No reset staged. Start with /resetdata.'
        try:
            staged_at = float(at_raw)
        except ValueError:
            staged_at = 0.0
        if time.time() - staged_at > PENDING_RESET_TTL_S:
            self.sessions.set_state(f'pending_reset_at:{chat_id}', '')
            return 'That staged reset expired after 10 minutes. Start again with /resetdata.'
        self.sessions.set_state(f'pending_reset_at:{chat_id}', '')
        try:
            result = self.tower_post('/api/tower/reset', {})
        except Exception:
            return (
                'Tower reset did NOT execute — the tower did not respond. '
                'Nothing was wiped; check /health and try /resetdata again.'
            )
        cancelled = result.get('cancelled_active') or []
        disturbed = (
            f"; cancelled {len(cancelled)} live search(es)" if cancelled else ''
        )
        return (
            f"🧹 Reset done — wiped {result.get('jobs', 0)} jobs · "
            f"{result.get('companies_unwatched_wiped', 0)} unwatched companies · "
            f"{result.get('runs', 0)} run records{disturbed}.\n"
            'Rebuild is already running: every search re-runs automatically, '
            'one by one, and each new catch gets full detail verification.'
        )

    def _push_stats(self) -> str:
        active = self.sessions.count_active_broadcast_subscribers()
        latest = self.sessions.latest_broadcast_push()
        if not latest:
            return f'No pushes sent yet. Active subscribers: {active}.'
        age = self._relative_age(latest['sent_at'])
        preview = _truncate_utf16(latest['text'] or '(photo only)', 200)
        return (
            f'LAST PUSH · {age}\n{preview}\n\n'
            f"Reached {latest['recipient_count']} · 👍 {latest['like_count']} likes\n"
            f'Active subscribers now: {active}'
        )

    def _configure_command_menu(self) -> bool:
        """Public menu is reverse prompt. Owner chat also gets ops commands."""
        try:
            for scope_type in ('default', 'all_private_chats'):
                self.api.call(
                    'setMyCommands',
                    {
                        'scope': json.dumps({'type': scope_type}),
                        'commands': json.dumps(PUBLIC_MENU),
                    },
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
        """Never send Thinking… — Prompt Tower answers in one line."""
        return False

    def _handle_alert_or_push_callback(self, chat_id: str, payload: str) -> ButtonReply | None:
        """Alert/push taps can arrive from a delivered alert or broadcast at
        ANY time — independent of wherever the guest's own button-flow
        session currently is — so these are handled here, before
        ButtonFlow ever sees them, rather than as one more ButtonFlow stage.
        Returns None for anything else so the caller falls through."""
        if payload.startswith('alert:off:'):
            raw_id = payload[len('alert:off:'):]
            alert = self.sessions.get_job_alert(int(raw_id)) if raw_id.isdigit() else None
            if alert is None or str(alert['chat_id']) != str(chat_id):
                return ButtonReply('That alert is no longer active.')
            self.sessions.deactivate_job_alert(alert['id'], chat_id)
            if alert.get('source') == 'auto':
                # 🔕 on an auto alert is a real opt-out: future searches stop
                # auto-subscribing until the guest taps "🔔 Set alert" again —
                # never silently re-enrol someone who just said stop.
                telegram_alerts.set_auto_opt_out(self.sessions, chat_id, True)
                return ButtonReply(
                    f"🔕 Stopped the daily alert for {alert['role_label']}. "
                    "I won't set alerts from your searches automatically anymore — "
                    'tap "🔔 Set alert" on any results to turn them back on.'
                )
            return ButtonReply(f"🔕 Stopped the alert for {alert['role_label']}.")
        if payload.startswith('alert:like:'):
            raw_id = payload[len('alert:like:'):]
            if raw_id.isdigit():
                self.sessions.like_job_alert(int(raw_id))
            return ButtonReply('Thanks for the feedback! 👍')
        if payload == 'push:stop':
            telegram_broadcast.stop(self.sessions, chat_id)
            return ButtonReply(
                "🔕 You won't receive further updates. Send /igtovid anytime to come back."
            )
        if payload.startswith('push:like:'):
            raw_id = payload[len('push:like:'):]
            if raw_id.isdigit():
                self.sessions.like_broadcast_push(int(raw_id))
            return ButtonReply('Thanks for the feedback! 👍')
        return None

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
        """Public reverse must answer in one line and never leak job copy."""
        reply = self.deck.handle_command(chat_id, 'igtovid', query)
        text = reply.text if isinstance(reply, ButtonReply) else str(reply)
        low = text.lower()
        if any(marker in low for marker in ('jobmaster', 'linkedin', 'verified job', 'job-market')):
            raise RuntimeError(f'prompt smoke leaked job copy: {text[:120]}')
        if isinstance(reply, ButtonReply):
            self.api.send_keyboard(chat_id, reply.text, reply.keyboard)
        else:
            self.api.send(chat_id, text)

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
            payload = clean[len(BTN_PREFIX):]
            # Prompt Tower deck taps — every user (Ashok 2026-09-12).
            if payload.startswith(PROMPT_CALLBACK_PREFIX):
                action = payload[len(PROMPT_CALLBACK_PREFIX):].split(':', 1)[0]
                if action in OWNER_DECK_ACTIONS and not self._effective_is_owner(chat_id):
                    self._send_button_reply(chat_id, ButtonReply(REVERSE_ASK), update_id=update_id)
                    return
                deck_reply = self.deck.handle_callback(chat_id, payload)
                self._send_button_reply(chat_id, deck_reply, update_id=update_id)
                if self.health_enabled:
                    self._write_health(
                        status='running', last_result='ok', last_chat=chat_id, last_kind='prompt_deck',
                    )
                return
            # Owner /topfreshers "More gems ▸" must page the gems session
            # before the guest ButtonFlow hijacks a bare `more` callback.
            if payload == 'more' and self._effective_is_owner(chat_id):
                gems = self._continue_topfreshers(chat_id)
                if gems is not None:
                    if isinstance(gems, ButtonReply):
                        self._send_button_reply(chat_id, gems, update_id=update_id)
                    else:
                        if update_id is not None and self.sessions.load_update_reply(update_id) is None:
                            self.sessions.save_update_reply(update_id, gems)
                        self.api.send(chat_id, gems)
                    if self.health_enabled:
                        self._write_health(
                            status='running', last_result='ok', last_chat=chat_id,
                            last_kind='topfreshers_more',
                        )
                    return
            button_reply = self._handle_alert_or_push_callback(chat_id, payload)
            if button_reply is None:
                button_reply = ButtonReply(REVERSE_ASK)
            self._send_button_reply(chat_id, button_reply, update_id=update_id)
            if self.health_enabled:
                self._write_health(
                    status='running', last_result='ok', last_chat=chat_id, last_kind='button',
                )
            return
        # Typed "more" after /topfreshers — same pagination as the button.
        if MORE_RE.match(clean) and self._effective_is_owner(chat_id):
            gems = self._continue_topfreshers(chat_id)
            if gems is not None:
                if isinstance(gems, ButtonReply):
                    self._send_button_reply(chat_id, gems, update_id=update_id)
                else:
                    if update_id is not None and self.sessions.load_update_reply(update_id) is None:
                        self.sessions.save_update_reply(update_id, gems)
                    self.api.send(chat_id, gems)
                self._page_count += 1
                if self.health_enabled:
                    self._write_health(
                        status='running', last_result='ok', last_chat=chat_id,
                        last_kind='topfreshers_more', last_text='more',
                        page_count=self._page_count,
                    )
                return
        parsed = self._command(clean)
        if parsed and parsed[0] in REVERSE_INTAKE_COMMANDS:
            command, arg = parsed
            try:
                reply = self.deck.handle_command(chat_id, command, arg)
            except Exception:
                LOG.exception('reverse command failed chat=%s command=%s', chat_id, command)
                reply = REVERSE_ASK
            self._send_button_reply(chat_id, reply if isinstance(reply, ButtonReply) else ButtonReply(str(reply)), update_id=update_id)
            if self.health_enabled:
                self._write_health(
                    status='running', last_result='ok', last_chat=chat_id,
                    last_kind='reverse_prompt', last_text=f'/{command}',
                )
            return
        if parsed and (
            parsed[0] in OWNER_COMMANDS
            or (parsed[0] == 'help' and self._effective_is_owner(chat_id))
        ):
            command, arg = parsed
            if command in OWNER_ROLE_SWITCH_COMMANDS and self._is_owner(chat_id):
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
                    reply = 'Tower could not reach live data. Try again shortly.'
            else:
                reply = REVERSE_ASK
            if isinstance(reply, ButtonReply):
                self._send_button_reply(chat_id, reply, update_id=update_id)
            else:
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
        reverse = (
            self.deck.maybe_take_twist(chat_id, clean)
            or self.deck.maybe_take_title(chat_id, clean)
            or self.deck.maybe_take_url(chat_id, clean)
        )
        if reverse is not None:
            self._send_button_reply(chat_id, reverse, update_id=update_id)
            if self.health_enabled:
                self._write_health(
                    status='running', last_result='ok', last_chat=chat_id,
                    last_kind='reverse_prompt', last_text=clean[:120],
                )
            return
        if clean.lower() in {'/start', '/help', 'help', '/myalerts'} or GREETING_RE.match(clean):
            reply = self.deck.handle_command(chat_id, 'igtovid', '')
            self._send_button_reply(chat_id, reply, update_id=update_id)
            return
        if update_id is not None and self.sessions.load_update_reply(update_id) is None:
            self.sessions.save_update_reply(update_id, REVERSE_ASK)
        self.api.send(chat_id, REVERSE_ASK)
        if self.health_enabled:
            self._write_health(
                status='running',
                last_result='ok',
                last_chat=chat_id,
                last_kind='reverse_prompt',
                last_text=clean[:120],
            )

    @staticmethod
    def _normalize_update(update: dict) -> tuple[bool, dict, dict, str | None, str | None, str]:
        """Fold a raw Telegram update (a `message` or a `callback_query`,
        see `allowed_updates` in `TelegramAPI.updates`) into one common
        shape the poll loop can dispatch uniformly. A button tap is
        re-encoded as BTN_PREFIX-tagged text so it flows through the exact
        same durable per-chat queue as typed messages (see queue_update) —
        callers never need a second code path for it.

        A photo message's caption stands in for `text` (so "/push <msg>" as
        a photo caption parses exactly like a typed command), and the
        largest photo size's file_id is returned separately — used only by
        the owner /push flow (see run()); guests never send photos here.

        A forwarded video (or a video document) keeps its file_id in the
        same extra slot as a photo when there is no photo — the poll loop
        distinguishes via `_video_file_id` on the raw message."""
        callback = update.get('callback_query')
        if callback:
            message = callback.get('message') or {}
            chat = message.get('chat') or {}
            sender = callback.get('from') or {}
            data = callback.get('data')
            text = f'{BTN_PREFIX}{data}' if isinstance(data, str) else None
            return True, chat, sender, text, callback.get('id'), ''
        message = update.get('message') or {}
        chat = message.get('chat') or {}
        sender = message.get('from') or {}
        photo_sizes = message.get('photo') or []
        photo_file_id = str(photo_sizes[-1].get('file_id') or '') if photo_sizes else ''
        text = message.get('text')
        if text is None and (photo_file_id or JobMasterTelegramBot._video_file_id(message)):
            text = message.get('caption')
        return False, chat, sender, text, None, photo_file_id

    @staticmethod
    def _video_file_id(message: dict) -> str:
        """Telegram `message.video` or a document whose mime is video/*."""
        video = (message or {}).get('video') or {}
        if video.get('file_id'):
            return str(video['file_id'])
        document = (message or {}).get('document') or {}
        mime = str(document.get('mime_type') or '')
        if mime.startswith('video/') and document.get('file_id'):
            return str(document['file_id'])
        return ''

    def run(self) -> int:
        self.api.call('deleteWebhook', {'drop_pending_updates': 'false'})
        me = self.api.call('getMe').get('result') or {}
        LOG.info('Prompt Tower Telegram started bot=@%s', me.get('username', 'unknown'))
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
                        is_callback, chat, sender, text, callback_id, photo_file_id = (
                            self._normalize_update(update)
                        )
                        video_file_id = (
                            '' if is_callback
                            else self._video_file_id(update.get('message') or {})
                        )
                        if (
                            text is None
                            and photo_file_id
                            and chat.get('id') is not None
                        ):
                            text = PROMPT_PHOTO_TAP
                        elif (
                            text is None
                            and video_file_id
                            and chat.get('id') is not None
                        ):
                            text = PROMPT_VIDEO_TAP
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
                                    telegram_broadcast.record_activity(self.sessions, chat_id)
                                elif photo_file_id:
                                    if self._is_owner(chat_id):
                                        self.sessions.set_state(
                                            f'pending_push_photo:{chat_id}', photo_file_id,
                                        )
                                    self.sessions.set_state(
                                        PROMPT_PHOTO_STATE.format(chat=chat_id), photo_file_id,
                                    )
                                elif video_file_id:
                                    self.sessions.set_state(
                                        PROMPT_VIDEO_STATE.format(chat=chat_id), video_file_id,
                                    )
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
                                        # Prompt commands can wait on Ollama
                                        # scoring — never block the poll loop.
                                        and parsed[0] not in PROMPT_COMMANDS
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


ALERT_DISPATCH_CHECK_S = 1800  # wake every 30 min; actually dispatches at most once/UTC day


def _run_alert_dispatch_loop(bot: 'JobMasterTelegramBot') -> None:
    """Background "set alert" scheduler living in this same process — the
    only process that already holds the Telegram credentials and the exact
    matching/formatting code (JobMasterEngine's HTTP client + _matches_role)
    an alert needs, so this avoids wiring Telegram sending into a second
    process (the Celery worker) just for this."""
    while not STOP:
        try:
            if telegram_alerts.should_dispatch_today(bot.sessions):
                sent = telegram_alerts.dispatch_due_alerts(
                    bot.sessions,
                    bot.engine.api_get,
                    lambda cid, text, kb: bot.api.send_keyboard(cid, text, kb),
                )
                telegram_alerts.mark_dispatched_today(bot.sessions)
                LOG.info('job alert dispatch complete: %s alert(s) sent', sent)
        except Exception:
            LOG.exception('job alert dispatch failed')
        for _ in range(ALERT_DISPATCH_CHECK_S // 10):
            if STOP:
                return
            time.sleep(10)


def _run_prompt_daily_loop(bot: 'JobMasterTelegramBot') -> None:
    """Prompt Tower daily deck: the Celery beat builds today's top-10; this
    loop notices it and sends it to Ashok exactly once per UTC day —
    proactive, never waiting for him to remember /prompts."""
    while not STOP:
        try:
            if bot.owner_chat_ids and bot.deck.daily_push_due():
                if bot.deck.deliver_daily(
                    bot.owner_chat_ids,
                    lambda cid, text, kb: bot.api.send_keyboard(cid, text, kb),
                ):
                    LOG.info('prompt daily deck delivered')
        except Exception:
            LOG.exception('prompt daily deck failed')
        for _ in range(PROMPT_DAILY_CHECK_S // 10):
            if STOP:
                return
            time.sleep(10)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Prompt Tower Telegram service')
    parser.add_argument('command', nargs='?', default='run', choices=['run', 'smoke'])
    parser.add_argument('--chat', default='')
    parser.add_argument('--query', default='')
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
    prompt_thread = threading.Thread(
        target=_run_prompt_daily_loop, args=(bot,), daemon=True, name='prompt-daily-deck',
    )
    prompt_thread.start()
    return bot.run()


if __name__ == '__main__':
    raise SystemExit(main())
