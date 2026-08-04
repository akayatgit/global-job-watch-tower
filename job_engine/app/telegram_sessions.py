"""Small, durable per-chat state for JobMaster Telegram pagination."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from app import config

DEFAULT_DB = config.BASE_DIR / '.data' / 'jobmaster_telegram.db'


class TelegramSessionStore:
    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS search_sessions (
                    chat_id TEXT PRIMARY KEY,
                    intent_json TEXT NOT NULL,
                    page INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def save_search(self, chat_id: str, intent: dict[str, Any], page: int = 0) -> None:
        payload = json.dumps(intent, separators=(',', ':'), ensure_ascii=False)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO search_sessions(chat_id, intent_json, page, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    intent_json=excluded.intent_json,
                    page=excluded.page,
                    updated_at=excluded.updated_at
                """,
                (str(chat_id), payload, max(0, int(page)), time.time()),
            )

    def load_search(self, chat_id: str) -> tuple[dict[str, Any], int] | None:
        with self._connect() as conn:
            row = conn.execute(
                'SELECT intent_json, page FROM search_sessions WHERE chat_id=?',
                (str(chat_id),),
            ).fetchone()
        if row is None:
            return None
        try:
            intent = json.loads(row['intent_json'])
        except (TypeError, json.JSONDecodeError):
            return None
        return intent, max(0, int(row['page']))

    def advance(self, chat_id: str) -> tuple[dict[str, Any], int] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                'SELECT intent_json, page FROM search_sessions WHERE chat_id=?',
                (str(chat_id),),
            ).fetchone()
            if row is None:
                return None
            page = max(0, int(row['page'])) + 1
            conn.execute(
                'UPDATE search_sessions SET page=?, updated_at=? WHERE chat_id=?',
                (page, time.time(), str(chat_id)),
            )
        try:
            return json.loads(row['intent_json']), page
        except (TypeError, json.JSONDecodeError):
            return None

    def clear(self, chat_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute('DELETE FROM search_sessions WHERE chat_id=?', (str(chat_id),))

    def get_state(self, key: str, default: str = '') -> str:
        with self._connect() as conn:
            row = conn.execute('SELECT value FROM bot_state WHERE key=?', (key,)).fetchone()
        return str(row['value']) if row else default

    def set_state(self, key: str, value: str | int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO bot_state(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, str(value)),
            )
