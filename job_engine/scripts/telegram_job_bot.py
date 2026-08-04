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
import os
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

from app.telegram_job_search import MORE_RE, RESET_RE, JobMasterEngine  # noqa: E402
from app.telegram_sessions import TelegramSessionStore  # noqa: E402

HERMES_ENV = Path.home() / '.hermes' / '.env'
HEALTH_FILE = ROOT / '.data' / 'jobmaster_telegram_health.json'
VERSION_FILE = ROOT.parent / 'VERSION'
LOG = logging.getLogger('jobmaster-telegram')
STOP = False
HEALTH_LOCK = threading.Lock()


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
        while remaining:
            chunk, remaining = remaining[:4000], remaining[4000:]
            self.call('sendMessage', {
                'chat_id': str(chat_id),
                'text': chunk,
                'disable_web_page_preview': 'true',
            })

    def updates(self, offset: int, timeout: int = 25) -> list[dict]:
        result = self.call(
            'getUpdates',
            {'offset': offset, 'timeout': timeout, 'allowed_updates': json.dumps(['message'])},
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
    ):
        self.api = api
        self.sessions = sessions or TelegramSessionStore()
        self.engine = engine or JobMasterEngine(sessions=self.sessions)
        self.health_enabled = health_enabled
        self._last_request: dict[str, float] = {}
        self._chat_locks: dict[str, threading.Lock] = {}
        self._chat_locks_guard = threading.Lock()
        self._queue_guard = threading.Lock()
        self._chat_queues: dict[str, deque[tuple[int, str, bool]]] = {}
        self._active_chats: set[str] = set()
        self._query_count = 0
        self._page_count = 0

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

    def _process_queued(
        self,
        update_id: int,
        chat_id: str,
        text: str,
        *,
        acked: bool = False,
    ) -> bool:
        prepared = self.sessions.load_update_reply(update_id)
        if prepared is not None:
            try:
                self.api.send(chat_id, prepared)
            except Exception as exc:
                LOG.exception('prepared Telegram delivery failed chat=%s', chat_id)
                if self.health_enabled:
                    self._write_health(status='degraded', error=str(exc)[:200])
                return False
            self.sessions.complete_update(update_id)
            return True
        if self._safe_process(chat_id, text, acked=acked, update_id=update_id):
            self.sessions.complete_update(update_id)
            return True
        return False

    def _enqueue_update(
        self,
        workers: ThreadPoolExecutor,
        update_id: int,
        chat_id: str,
        text: str,
        *,
        acked: bool = False,
    ) -> None:
        with self._queue_guard:
            queue = self._chat_queues.setdefault(chat_id, deque())
            queue.append((update_id, text, acked))
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
                update_id, text, acked = queue.popleft()
            if self._process_queued(update_id, chat_id, text, acked=acked):
                retry_delay = 1
                failures = 0
                continue
            with self._queue_guard:
                self._chat_queues.setdefault(chat_id, deque()).appendleft(
                    (update_id, text, acked)
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
        if not clean or RESET_RE.match(clean) or clean.lower() in {'/start', '/help', 'help'}:
            return False
        try:
            self.api.send(chat_id, 'Thinking…')
            return True
        except Exception:
            LOG.exception('immediate acknowledgement failed chat=%s', chat_id)
            return False

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
        is_reset = bool(RESET_RE.match(clean))
        if clean.lower() in {'/start', '/help', 'help'}:
            reply = (
                'JobMaster provides verified jobs and live job-market insights. '
                'Ask naturally in any sentence.'
            )
            if update_id is not None:
                self.sessions.save_update_reply(update_id, reply)
            self.api.send(chat_id, reply)
            return
        if not is_reset:
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
        if update_id is not None and self.sessions.load_update_reply(update_id) is None:
            self.sessions.save_update_reply(update_id, reply)
        self.api.send(chat_id, reply)
        if is_reset:
            self._last_request.pop(chat_id, None)
        else:
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

    def run(self) -> int:
        self.api.call('deleteWebhook', {'drop_pending_updates': 'false'})
        me = self.api.call('getMe').get('result') or {}
        LOG.info('JobMaster Telegram started bot=@%s', me.get('username', 'unknown'))
        offset_raw = self.sessions.get_state('telegram_update_offset', '')
        if offset_raw.isdigit():
            offset = int(offset_raw)
        else:
            # First dedicated start consumes the Bot API queue normally. Hermes
            # was stopped first, so messages arriving during cutover must not
            # be drained or silently lost.
            offset = 0
            self.sessions.set_state('telegram_update_offset', offset)
        self._write_health(status='running', bot=me.get('username', ''))

        backoff = 1
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix='jobmaster') as workers:
            for update_id, chat_id, text in self.sessions.pending_updates():
                self._enqueue_update(workers, update_id, chat_id, text)
            while not STOP:
                try:
                    updates = self.api.updates(offset)
                    backoff = 1
                    self._write_health(status='running', bot=me.get('username', ''))
                    for update in updates:
                        update_id = int(update.get('update_id', -1))
                        offset = max(offset, update_id + 1)
                        message = update.get('message') or {}
                        chat = message.get('chat') or {}
                        if chat.get('type') == 'private' and chat.get('id'):
                            text = message.get('text')
                            if isinstance(text, str):
                                chat_id = str(chat['id'])
                                if self.sessions.queue_update(update_id, chat_id, text):
                                    acked = self._pre_ack(chat_id, text)
                                    self._enqueue_update(
                                        workers,
                                        update_id,
                                        chat_id,
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
    bot = JobMasterTelegramBot(api, health_enabled=args.command != 'smoke')
    if args.command == 'smoke':
        if not args.chat:
            parser.error('smoke requires --chat')
        bot.process(args.chat, args.query)
        return 0
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    return bot.run()


if __name__ == '__main__':
    raise SystemExit(main())
