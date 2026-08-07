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
                CREATE TABLE IF NOT EXISTS job_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    role_family TEXT NOT NULL DEFAULT '',
                    role_keywords_json TEXT NOT NULL DEFAULT '[]',
                    role_label TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL DEFAULT '',
                    experience TEXT NOT NULL DEFAULT 'fresher',
                    active INTEGER NOT NULL DEFAULT 1,
                    sent_job_ids_json TEXT NOT NULL DEFAULT '[]',
                    likes INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_job_alerts_chat_active
                    ON job_alerts(chat_id, active);
                CREATE INDEX IF NOT EXISTS ix_job_alerts_active
                    ON job_alerts(active);
                CREATE TABLE IF NOT EXISTS broadcast_subscribers (
                    chat_id TEXT PRIMARY KEY,
                    active INTEGER NOT NULL DEFAULT 1,
                    pushes_since_response INTEGER NOT NULL DEFAULT 0,
                    pushes_received INTEGER NOT NULL DEFAULT 0,
                    started_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_broadcast_subscribers_active
                    ON broadcast_subscribers(active);
                CREATE TABLE IF NOT EXISTS broadcast_pushes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL DEFAULT '',
                    photo_file_id TEXT NOT NULL DEFAULT '',
                    sent_at REAL NOT NULL,
                    recipient_count INTEGER NOT NULL DEFAULT 0,
                    like_count INTEGER NOT NULL DEFAULT 0
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
            broadcast_columns = {
                row[1]
                for row in conn.execute('PRAGMA table_info(broadcast_subscribers)').fetchall()
            }
            if 'pushes_received' not in broadcast_columns:
                conn.execute(
                    'ALTER TABLE broadcast_subscribers ADD COLUMN '
                    'pushes_received INTEGER NOT NULL DEFAULT 0'
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
            self._backfill_broadcast_subscribers(conn)

    def _backfill_broadcast_subscribers(self, conn: sqlite3.Connection) -> None:
        """Ashok (2026-08-07): "everyone who are guests is the only
        condition" for a push — not only chats that tap /start AFTER this
        feature shipped. Guests with history from before this table existed
        (azr0099, supriyamk, cryptoonz, ...) must show up too, without
        having to message the bot again first. Runs on every store startup
        (same idempotent-maintenance pattern as the history prune above);
        INSERT OR IGNORE never touches a chat_id already tracked here, so an
        explicit stop or an in-progress unanswered-push count is untouched —
        this only ever adds a never-before-seen guest as freshly active."""
        owner_row = conn.execute(
            "SELECT value FROM bot_state WHERE key='telegram_command_owner_ids'",
        ).fetchone()
        owner_ids = {
            value for value in (owner_row[0].split(',') if owner_row and owner_row[0] else [])
            if value
        }
        rows = conn.execute(
            """
            SELECT DISTINCT chat_id FROM (
                SELECT chat_id FROM conversation_history
                UNION SELECT chat_id FROM guest_profiles
                UNION SELECT chat_id FROM onboarding_sessions
            )
            """
        ).fetchall()
        now = time.time()
        for row in rows:
            chat_id = str(row[0])
            if chat_id in owner_ids:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO broadcast_subscribers(
                    chat_id, active, pushes_since_response, started_at, last_seen_at, updated_at
                )
                VALUES (?, 1, 0, ?, ?, ?)
                """,
                (chat_id, now, now, now),
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

    # -- job alerts (2026-08-07) -------------------------------------------
    # "Set alert every day" on a completed search: remember the criteria,
    # and only ever notify about jobs not already in sent_job_ids_json —
    # subscribing seeds that list with whatever the guest already saw, so
    # the very next daily check never re-announces old results.

    @staticmethod
    def _job_alert_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        try:
            keywords = json.loads(row['role_keywords_json'] or '[]')
        except (TypeError, json.JSONDecodeError):
            keywords = []
        try:
            sent_ids = json.loads(row['sent_job_ids_json'] or '[]')
        except (TypeError, json.JSONDecodeError):
            sent_ids = []
        return {
            'id': int(row['id']),
            'chat_id': str(row['chat_id']),
            'role_family': str(row['role_family'] or ''),
            'role_keywords': [str(w) for w in keywords] if isinstance(keywords, list) else [],
            'role_label': str(row['role_label'] or ''),
            'city': str(row['city'] or ''),
            'experience': str(row['experience'] or 'fresher'),
            'active': bool(row['active']),
            'sent_job_ids': [str(x) for x in sent_ids] if isinstance(sent_ids, list) else [],
            'likes': int(row['likes']),
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
        }

    def find_job_alert(
        self,
        chat_id: str,
        *,
        role_family: str,
        role_keywords: list[str] | None,
        city: str,
        experience: str,
    ) -> dict[str, Any] | None:
        key = json.dumps(
            sorted({str(w).strip().lower() for w in (role_keywords or []) if str(w).strip()}),
            separators=(',', ':'),
        )
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM job_alerts
                WHERE chat_id=? AND active=1 AND role_family=? AND city=? AND experience=?
                """,
                (str(chat_id), role_family or '', city or '', experience or 'fresher'),
            ).fetchall()
        for row in rows:
            existing_key = json.dumps(
                sorted({
                    str(w).strip().lower()
                    for w in (json.loads(row['role_keywords_json'] or '[]') or [])
                    if str(w).strip()
                }),
                separators=(',', ':'),
            )
            if existing_key == key:
                return self._job_alert_row_to_dict(row)
        return None

    def count_active_job_alerts(self, chat_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                'SELECT COUNT(*) AS n FROM job_alerts WHERE chat_id=? AND active=1',
                (str(chat_id),),
            ).fetchone()
        return int(row['n']) if row else 0

    def create_job_alert(
        self,
        chat_id: str,
        *,
        role_family: str = '',
        role_keywords: list[str] | None = None,
        role_label: str = '',
        city: str = '',
        experience: str = 'fresher',
        seen_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        payload = json.dumps(list(role_keywords or []), separators=(',', ':'))
        sent_payload = json.dumps(
            list(dict.fromkeys(str(x) for x in (seen_ids or []))),
            separators=(',', ':'),
        )
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO job_alerts(
                    chat_id, role_family, role_keywords_json, role_label, city,
                    experience, active, sent_job_ids_json, likes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, 0, ?, ?)
                """,
                (
                    str(chat_id), role_family or '', payload, role_label or '',
                    city or '', experience or 'fresher', sent_payload, now, now,
                ),
            )
            alert_id = int(cursor.lastrowid)
        alert = self.get_job_alert(alert_id)
        assert alert is not None
        return alert

    def get_job_alert(self, alert_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                'SELECT * FROM job_alerts WHERE id=?', (int(alert_id),),
            ).fetchone()
        return self._job_alert_row_to_dict(row) if row is not None else None

    def list_job_alerts(self, chat_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM job_alerts WHERE chat_id=? AND active=1
                ORDER BY created_at ASC
                """,
                (str(chat_id),),
            ).fetchall()
        return [self._job_alert_row_to_dict(row) for row in rows]

    def list_active_job_alerts_all(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT * FROM job_alerts WHERE active=1 ORDER BY id ASC',
            ).fetchall()
        return [self._job_alert_row_to_dict(row) for row in rows]

    def deactivate_job_alert(self, alert_id: int, chat_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE job_alerts SET active=0, updated_at=?
                WHERE id=? AND chat_id=? AND active=1
                """,
                (time.time(), int(alert_id), str(chat_id)),
            )
        return bool(cursor.rowcount)

    def like_job_alert(self, alert_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                'UPDATE job_alerts SET likes=likes+1, updated_at=? WHERE id=?',
                (time.time(), int(alert_id)),
            )
        return bool(cursor.rowcount)

    def mark_job_alert_sent(self, alert_id: int, job_ids: list[str], *, cap: int = 300) -> None:
        alert = self.get_job_alert(alert_id)
        if alert is None:
            return
        merged = list(dict.fromkeys([*alert['sent_job_ids'], *[str(x) for x in job_ids]]))
        if len(merged) > cap:
            merged = merged[-cap:]
        payload = json.dumps(merged, separators=(',', ':'))
        with self._lock, self._connect() as conn:
            conn.execute(
                'UPDATE job_alerts SET sent_job_ids_json=?, updated_at=? WHERE id=?',
                (payload, time.time(), int(alert_id)),
            )

    # -- broadcast / push notifications (2026-08-07) -----------------------
    # Everyone who has tapped "start" is a broadcast subscriber. Any
    # interaction with the bot marks them responsive again; 3 consecutive
    # unanswered pushes temporarily removes them (see record_broadcast_sent)
    # so JobMaster never looks like a spammy dead-air bot on Telegram's own
    # abuse radar — but the very next message they send brings them right
    # back (record_broadcast_activity), no manual re-opt-in needed.

    def record_broadcast_start(self, chat_id: str) -> None:
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO broadcast_subscribers(
                    chat_id, active, pushes_since_response, started_at, last_seen_at, updated_at
                )
                VALUES (?, 1, 0, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    active=1,
                    pushes_since_response=0,
                    last_seen_at=excluded.last_seen_at,
                    updated_at=excluded.updated_at
                """,
                (str(chat_id), now, now, now),
            )

    def record_broadcast_activity(self, chat_id: str) -> None:
        """Ashok (2026-08-07): "everyone who are guests is the only
        condition" — ANY message from a guest enrolls/reactivates them, not
        only a literal /start tap (a guest whose first-ever message is a
        fully specified query, e.g. "AI jobs in Bangalore", never routes
        through ButtonFlow.start() at all). Functionally identical to
        record_broadcast_start; kept as a separate method so call sites
        stay self-documenting (the entry-point tap vs. "any activity")."""
        self.record_broadcast_start(chat_id)

    def stop_broadcast(self, chat_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                'UPDATE broadcast_subscribers SET active=0, updated_at=? WHERE chat_id=?',
                (time.time(), str(chat_id)),
            )

    def list_active_broadcast_subscribers(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT chat_id FROM broadcast_subscribers WHERE active=1 ORDER BY started_at ASC',
            ).fetchall()
        return [str(row['chat_id']) for row in rows]

    def count_active_broadcast_subscribers(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                'SELECT COUNT(*) AS n FROM broadcast_subscribers WHERE active=1',
            ).fetchone()
        return int(row['n']) if row else 0

    def broadcast_pushes_received_map(self, chat_ids: list[str]) -> dict[str, int]:
        """How many pushes each chat has already received, lifetime — used
        to decide who is first-timer (gets the 🔕 Stop notifications button
        + hint line) vs. a repeat recipient (Ashok, 2026-08-07: "only in 1st
        broadcast for every user is enough" — the button stays clickable
        forever on that first message, so nobody loses the ability to stop,
        it just isn't repeated on every push)."""
        if not chat_ids:
            return {}
        placeholders = ','.join('?' for _ in chat_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT chat_id, pushes_received FROM broadcast_subscribers
                WHERE chat_id IN ({placeholders})
                """,
                [str(c) for c in chat_ids],
            ).fetchall()
        return {str(row['chat_id']): int(row['pushes_received']) for row in rows}

    def create_broadcast_push(self, *, text: str = '', photo_file_id: str = '') -> int:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO broadcast_pushes(text, photo_file_id, sent_at, recipient_count, like_count)
                VALUES (?, ?, ?, 0, 0)
                """,
                (text or '', photo_file_id or '', time.time()),
            )
            return int(cursor.lastrowid)

    def record_broadcast_sent(self, push_id: int, chat_id: str, *, max_unanswered: int = 3) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                'UPDATE broadcast_pushes SET recipient_count=recipient_count+1 WHERE id=?',
                (int(push_id),),
            )
            conn.execute(
                """
                UPDATE broadcast_subscribers
                SET pushes_since_response=pushes_since_response+1,
                    pushes_received=pushes_received+1,
                    updated_at=?
                WHERE chat_id=?
                """,
                (time.time(), str(chat_id)),
            )
            conn.execute(
                """
                UPDATE broadcast_subscribers SET active=0, updated_at=?
                WHERE chat_id=? AND pushes_since_response>=?
                """,
                (time.time(), str(chat_id), int(max_unanswered)),
            )

    def like_broadcast_push(self, push_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                'UPDATE broadcast_pushes SET like_count=like_count+1 WHERE id=?',
                (int(push_id),),
            )
        return bool(cursor.rowcount)

    def latest_broadcast_push(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                'SELECT * FROM broadcast_pushes ORDER BY id DESC LIMIT 1',
            ).fetchone()
        if row is None:
            return None
        return {
            'id': int(row['id']),
            'text': str(row['text'] or ''),
            'photo_file_id': str(row['photo_file_id'] or ''),
            'sent_at': float(row['sent_at']),
            'recipient_count': int(row['recipient_count']),
            'like_count': int(row['like_count']),
        }
