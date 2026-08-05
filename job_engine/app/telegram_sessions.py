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


class AmbiguousTelegramIdentity(ValueError):
    """A mutable username has belonged to more than one numeric chat."""


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
                CREATE TABLE IF NOT EXISTS conversation_history (
                    update_id INTEGER PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    user_text TEXT NOT NULL,
                    bot_reply TEXT NOT NULL,
                    completed_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_conversation_history_chat
                    ON conversation_history(chat_id, completed_at DESC);
                CREATE INDEX IF NOT EXISTS ix_conversation_history_username
                    ON conversation_history(username COLLATE NOCASE, completed_at DESC);
                CREATE TABLE IF NOT EXISTS onboarding_sessions (
                    chat_id TEXT PRIMARY KEY,
                    stage TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS guest_profiles (
                    chat_id TEXT PRIMARY KEY,
                    role_label TEXT NOT NULL DEFAULT '',
                    role_family TEXT NOT NULL DEFAULT '',
                    role_keywords_json TEXT NOT NULL DEFAULT '[]',
                    experience TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
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
            # Enforce the product's strict privacy cap for databases created by
            # older builds, not only when the next conversation arrives.
            conn.execute(
                """
                DELETE FROM conversation_history
                WHERE update_id IN (
                    SELECT update_id
                    FROM (
                        SELECT
                            update_id,
                            ROW_NUMBER() OVER (
                                PARTITION BY chat_id
                                ORDER BY completed_at DESC, update_id DESC
                            ) AS row_number
                        FROM conversation_history
                    )
                    WHERE row_number > 40
                )
                """
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

    def record_conversation(
        self,
        update_id: int,
        chat_id: str,
        username: str,
        user_text: str,
        bot_reply: str,
        *,
        completed_at: float | None = None,
        retention_per_chat: int = 40,
    ) -> None:
        """Idempotently retain a delivered user message + final bot reply."""
        keep = max(1, min(int(retention_per_chat), 40))
        with self._lock, self._connect() as conn:
            self._record_conversation(
                conn,
                update_id,
                chat_id,
                username,
                user_text,
                bot_reply,
                completed_at=completed_at,
                keep=keep,
            )

    @staticmethod
    def _record_conversation(
        conn: sqlite3.Connection,
        update_id: int,
        chat_id: str,
        username: str,
        user_text: str,
        bot_reply: str,
        *,
        completed_at: float | None,
        keep: int,
    ) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO conversation_history(
                update_id, chat_id, username, user_text, bot_reply, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(update_id),
                str(chat_id),
                str(username or '').strip().lstrip('@').lower(),
                str(user_text),
                str(bot_reply),
                float(completed_at if completed_at is not None else time.time()),
            ),
        )
        conn.execute(
            """
            DELETE FROM conversation_history
            WHERE chat_id=?
              AND update_id NOT IN (
                SELECT update_id
                FROM conversation_history
                WHERE chat_id=?
                ORDER BY completed_at DESC, update_id DESC
                LIMIT ?
              )
            """,
            (str(chat_id), str(chat_id), keep),
        )

    def finalize_guest_conversation(
        self,
        update_id: int,
        chat_id: str,
        username: str,
        user_text: str,
        bot_reply: str,
    ) -> None:
        """Atomically archive a delivered guest reply and clear its inbox row."""
        with self._lock, self._connect() as conn:
            self._record_conversation(
                conn,
                update_id,
                chat_id,
                username,
                user_text,
                bot_reply,
                completed_at=None,
                keep=40,
            )
            conn.execute(
                'DELETE FROM telegram_inbox WHERE update_id=?',
                (int(update_id),),
            )

    @staticmethod
    def _resolve_chat_id_by_username(conn: sqlite3.Connection, username: str) -> str:
        """Stable numeric chat_id previously observed for a mutable @username.

        Fails closed (raises) when the handle is ambiguous rather than
        guessing which person it currently belongs to.
        """
        identities = conn.execute(
            """
            SELECT chat_id, MAX(completed_at) AS last_seen
            FROM conversation_history
            WHERE username = ? COLLATE NOCASE
            GROUP BY chat_id
            ORDER BY last_seen DESC
            """,
            (username,),
        ).fetchall()
        if len(identities) > 1:
            raise AmbiguousTelegramIdentity(
                f'@{username} has more than one stored Telegram ID'
            )
        if not identities:
            return ''
        return str(identities[0]['chat_id'])

    def save_onboarding(self, chat_id: str, state: dict[str, Any]) -> None:
        payload = json.dumps(state, separators=(',', ':'), ensure_ascii=False)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO onboarding_sessions(chat_id, stage, data_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    stage=excluded.stage,
                    data_json=excluded.data_json,
                    updated_at=excluded.updated_at
                """,
                (str(chat_id), str(state.get('stage') or ''), payload, time.time()),
            )

    def load_onboarding(self, chat_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                'SELECT data_json FROM onboarding_sessions WHERE chat_id=?',
                (str(chat_id),),
            ).fetchone()
        if row is None:
            return None
        try:
            data = json.loads(row['data_json'])
        except (TypeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def clear_onboarding(self, chat_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute('DELETE FROM onboarding_sessions WHERE chat_id=?', (str(chat_id),))

    def save_guest_profile(
        self,
        chat_id: str,
        *,
        role_label: str = '',
        role_family: str = '',
        role_keywords: list[str] | None = None,
        experience: str = '',
        city: str = '',
    ) -> None:
        payload = json.dumps(list(role_keywords or []), separators=(',', ':'))
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO guest_profiles(
                    chat_id, role_label, role_family, role_keywords_json,
                    experience, city, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    role_label=excluded.role_label,
                    role_family=excluded.role_family,
                    role_keywords_json=excluded.role_keywords_json,
                    experience=excluded.experience,
                    city=excluded.city,
                    updated_at=excluded.updated_at
                """,
                (
                    str(chat_id),
                    str(role_label or ''),
                    str(role_family or ''),
                    payload,
                    str(experience or ''),
                    str(city or ''),
                    time.time(),
                ),
            )

    def get_guest_profile(self, identity: str) -> dict[str, Any] | None:
        """Owner-only lookup by @username or numeric Telegram ID (JobMaster
        guest management). Same fail-closed ambiguous-username rule as
        conversation_history — never guesses across a renamed/recycled handle.
        """
        raw = str(identity or '').strip()
        if raw.startswith('@'):
            with self._connect() as conn:
                chat_id = self._resolve_chat_id_by_username(conn, raw[1:])
            if not chat_id:
                return None
        else:
            chat_id = raw
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT chat_id, role_label, role_family, role_keywords_json,
                       experience, city, updated_at
                FROM guest_profiles WHERE chat_id=?
                """,
                (chat_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            keywords = json.loads(row['role_keywords_json'] or '[]')
        except (TypeError, json.JSONDecodeError):
            keywords = []
        return {
            'chat_id': str(row['chat_id']),
            'role_label': str(row['role_label'] or ''),
            'role_family': str(row['role_family'] or ''),
            'role_keywords': [str(word) for word in keywords] if isinstance(keywords, list) else [],
            'experience': str(row['experience'] or ''),
            'city': str(row['city'] or ''),
            'updated_at': float(row['updated_at']),
        }

    def conversation_history(
        self,
        identity: str,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return oldest→newest within the requested latest window."""
        raw = str(identity or '').strip()
        count = max(1, min(int(limit), 40))
        if raw.startswith('@'):
            username = raw[1:]
            with self._connect() as conn:
                resolved = self._resolve_chat_id_by_username(conn, username)
            if not resolved:
                return []
            where = 'chat_id = ?'
            value = resolved
        elif raw.isdigit():
            where = 'chat_id = ?'
            value = raw
        else:
            where = 'username = ? COLLATE NOCASE'
            value = raw
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT update_id, chat_id, username, user_text, bot_reply, completed_at
                FROM conversation_history
                WHERE {where}
                ORDER BY completed_at DESC, update_id DESC
                LIMIT ?
                """,
                (value, count),
            ).fetchall()
        return [
            {
                'update_id': int(row['update_id']),
                'chat_id': str(row['chat_id']),
                'username': str(row['username'] or ''),
                'user_text': str(row['user_text']),
                'bot_reply': str(row['bot_reply']),
                'completed_at': float(row['completed_at']),
            }
            for row in reversed(rows)
        ]
