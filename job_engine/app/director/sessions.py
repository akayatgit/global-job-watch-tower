"""Persistent DIRECTOR memory via OpenAI Agents SDK SQLiteSession."""

from __future__ import annotations

import asyncio
from pathlib import Path

from agents import SQLiteSession

from app import config


def session_id(bot: str, chat_id: str) -> str:
    bot = (bot or 'vigil').strip().lstrip('@') or 'vigil'
    chat = (chat_id or 'unknown').strip()
    return f'{bot}:{chat}'


def get_session(bot: str, chat_id: str) -> SQLiteSession:
    db: Path = config.DIRECTOR_SESSION_DB
    db.parent.mkdir(parents=True, exist_ok=True)
    return SQLiteSession(session_id(bot, chat_id), str(db))


def clear_session(bot: str, chat_id: str) -> None:
    sess = get_session(bot, chat_id)
    asyncio.run(sess.clear_session())
