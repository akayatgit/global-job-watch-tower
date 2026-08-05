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
                    seen_json TEXT NOT NULL DEFAULT '[]',
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS telegram_inbox (
                    update_id INTEGER PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL,
                    reply TEXT,
                    created_at REAL NOT NULL
                );
                """
            )
            columns = {
                row[1] for row in conn.execute('PRAGMA table_info(search_sessions)').fetchall()
            }
            if 'seen_json' not in columns:
                conn.execute(
                    "ALTER TABLE search_sessions ADD COLUMN seen_json TEXT NOT NULL DEFAULT '[]'"
                )
            inbox_columns = {
                row[1] for row in conn.execute('PRAGMA table_info(telegram_inbox)').fetchall()
            }
            if 'reply' not in inbox_columns:
                conn.execute('ALTER TABLE telegram_inbox ADD COLUMN reply TEXT')
            if 'username' not in inbox_columns:
                conn.execute(
                    "ALTER TABLE telegram_inbox ADD COLUMN username TEXT NOT NULL DEFAULT ''"
                )

    def save_search(
        self,
        chat_id: str,
        intent: dict[str, Any],
        page: int = 0,
        seen_ids: list[str] | None = None,
    ) -> None:
        payload = json.dumps(intent, separators=(',', ':'), ensure_ascii=False)
        seen_payload = json.dumps(list(dict.fromkeys(seen_ids or [])), separators=(',', ':'))
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO search_sessions(chat_id, intent_json, page, seen_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    intent_json=excluded.intent_json,
                    page=excluded.page,
                    seen_json=excluded.seen_json,
                    updated_at=excluded.updated_at
                """,
                (
                    str(chat_id),
                    payload,
                    max(0, int(page)),
                    seen_payload,
                    time.time(),
                ),
            )

    def load_search(self, chat_id: str) -> tuple[dict[str, Any], int, list[str]] | None:
        with self._connect() as conn:
            row = conn.execute(
                'SELECT intent_json, page, seen_json FROM search_sessions WHERE chat_id=?',
                (str(chat_id),),
            ).fetchone()
        if row is None:
            return None
        try:
            intent = json.loads(row['intent_json'])
            seen = json.loads(row['seen_json'] or '[]')
        except (TypeError, json.JSONDecodeError):
            return None
        return intent, max(0, int(row['page'])), [str(value) for value in seen]

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

    def queue_update(
        self,
        update_id: int,
        chat_id: str,
        text: str,
        username: str = '',
    ) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO telegram_inbox(
                    update_id, chat_id, username, text, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (int(update_id), str(chat_id), str(username or ''), text, time.time()),
            )
        return bool(cursor.rowcount)

    def pending_updates(self) -> list[tuple[int, str, str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT update_id, chat_id, username, text
                FROM telegram_inbox
                ORDER BY update_id
                """
            ).fetchall()
        return [
            (
                int(row['update_id']),
                str(row['chat_id']),
                str(row['username'] or ''),
                str(row['text']),
            )
            for row in rows
        ]

    def complete_update(self, update_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute('DELETE FROM telegram_inbox WHERE update_id=?', (int(update_id),))

    def save_update_reply(self, update_id: int, reply: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                'UPDATE telegram_inbox SET reply=? WHERE update_id=?',
                (reply, int(update_id)),
            )

    def apply_result(
        self,
        chat_id: str,
        reply: str,
        *,
        update_id: int | None = None,
        intent: dict[str, Any] | None = None,
        page: int = 0,
        seen_ids: list[str] | None = None,
        clear_search: bool = False,
    ) -> None:
        """Atomically persist pagination/reset state and the outbound reply."""
        with self._lock, self._connect() as conn:
            if clear_search:
                conn.execute('DELETE FROM search_sessions WHERE chat_id=?', (str(chat_id),))
            elif intent is not None:
                payload = json.dumps(intent, separators=(',', ':'), ensure_ascii=False)
                seen_payload = json.dumps(
                    list(dict.fromkeys(seen_ids or [])),
                    separators=(',', ':'),
                )
                conn.execute(
                    """
                    INSERT INTO search_sessions(chat_id, intent_json, page, seen_json, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(chat_id) DO UPDATE SET
                        intent_json=excluded.intent_json,
                        page=excluded.page,
                        seen_json=excluded.seen_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        str(chat_id),
                        payload,
                        max(0, int(page)),
                        seen_payload,
                        time.time(),
                    ),
                )
            if update_id is not None:
                conn.execute(
                    'UPDATE telegram_inbox SET reply=? WHERE update_id=?',
                    (reply, int(update_id)),
                )

    def load_update_reply(self, update_id: int) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                'SELECT reply FROM telegram_inbox WHERE update_id=?',
                (int(update_id),),
            ).fetchone()
        if row is None or row['reply'] is None:
            return None
        return str(row['reply'])
