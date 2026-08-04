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
import time
import urllib.error
import urllib.parse
import urllib.request
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


def load_env() -> dict[str, str]:
    values = dict(os.environ)
    if HERMES_ENV.exists():
        for line in HERMES_ENV.read_text(encoding='utf-8').splitlines():
            if not line or line.lstrip().startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            values.setdefault(key.strip(), value.strip())
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
    ):
        self.api = api
        self.sessions = sessions or TelegramSessionStore()
        self.engine = engine or JobMasterEngine(sessions=self.sessions)
        self._last_request: dict[str, float] = {}
        self._query_count = 0
        self._page_count = 0

    def process(self, chat_id: str, text: str) -> None:
        clean = (text or '').strip()
        if not clean:
            return
        if clean.lower() in {'/start', '/help', 'help'}:
            self.api.send(
                chat_id,
                'JobMaster provides verified jobs and live job-market insights. '
                'Ask naturally in any sentence.',
            )
            return
        if not RESET_RE.match(clean):
            now = time.monotonic()
            last = self._last_request.get(chat_id, 0.0)
            if now - last < 1.0:
                self.api.send(chat_id, 'One request at a time.')
                return
            self._last_request[chat_id] = now
            self.api.send(chat_id, 'Thinking…')
        try:
            reply = self.engine.handle(clean, chat_id)
        except Exception:
            LOG.exception('request failed chat=%s text=%r', chat_id, clean[:120])
            reply = 'JobMaster could not reach live Watch Tower data. Try again shortly.'
        self.api.send(chat_id, reply)
        if MORE_RE.match(clean):
            self._page_count += 1
        else:
            self._query_count += 1
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
            # First dedicated start: acknowledge old updates without replaying them.
            pending = self.api.updates(0, timeout=0)
            offset = max([int(row.get('update_id', -1)) + 1 for row in pending] + [0])
            self.sessions.set_state('telegram_update_offset', offset)
        self._write_health(status='running', bot=me.get('username', ''))

        backoff = 1
        while not STOP:
            try:
                updates = self.api.updates(offset)
                backoff = 1
                self._write_health(status='running', bot=me.get('username', ''))
                for update in updates:
                    update_id = int(update.get('update_id', -1))
                    offset = max(offset, update_id + 1)
                    self.sessions.set_state('telegram_update_offset', offset)
                    message = update.get('message') or {}
                    chat = message.get('chat') or {}
                    if chat.get('type') != 'private' or not chat.get('id'):
                        continue
                    text = message.get('text')
                    if isinstance(text, str):
                        self.process(str(chat['id']), text)
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
    bot = JobMasterTelegramBot(api)
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
