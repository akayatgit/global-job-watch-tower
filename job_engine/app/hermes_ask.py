"""Bridge VIGIL Ask → board text (no LLM) or grounded Hermes (MCP-only)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai_capacity import compute_ai_capacity
from app.vigil_boards import BOARD_HELP, render_board, resolve_board

HERMES_BIN = Path.home() / '.local' / 'bin' / 'hermes'
ASK_QUEUE = Path(__file__).resolve().parents[1] / '.data' / 'hermes_ask_queue.jsonl'
MAX_PROMPT = 4000
MAX_TURNS = 8
TIMEOUT_S = 180

REFUSE = (
    'I won’t invent tower numbers.\n\n'
    'Use a live VIGIL board:\n'
    '/towerinsights  /health  /hiringsignals  /searches\n'
    '/watchlist  /fresh  /brief  /boards\n\n'
    'Or ask again when the tower is cool — I’ll only answer from MCP tools.'
)

# Natural phrases → board (deterministic; never invent via LLM)
_NL_BOARD = [
    (re.compile(r'\b(tower\s*insights?|/towerinsights?)\b', re.I), 'tower'),
    (re.compile(r'\b(tower\s*health|/health)\b', re.I), 'health'),
    (re.compile(r'\b(hiring\s*signals?|/hiringsignals?|/signals?)\b', re.I), 'signals'),
    (re.compile(r'\b(/searches?|list\s+roles|list\s+searches)\b', re.I), 'searches'),
    (re.compile(r'\b(/watchlist|watched\s+compan)\b', re.I), 'watchlist'),
    (re.compile(r'\b(fresh(est)?\s*catch(?:es)?|/fresh)\b', re.I), 'fresh'),
    (re.compile(r'\b(daily\s*brief|/brief)\b', re.I), 'brief'),
    (re.compile(r'\b(top\s+hir(e|ing)|who\s+is\s+hiring)\b', re.I), 'tower'),
]

_HIRING_INTENT = re.compile(
    r'\b(job|hiring|compan|role|opening|catch|signal|watchlist|salary|market|'
    r'sector|posted|scrape|tower|brief|recruit|talent)\b',
    re.I,
)


def _queue_prompt(prompt: str) -> None:
    ASK_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    with ASK_QUEUE.open('a', encoding='utf-8') as f:
        f.write(json.dumps({
            'ts': time.time(),
            'prompt': prompt[:MAX_PROMPT],
        }) + '\n')


def _try_board(prompt: str) -> str | None:
    text = (prompt or '').strip()
    if not text:
        return None
    m = re.match(r'^/([a-zA-Z]+)(?:\s+(\d+))?\s*$', text)
    if m:
        name, days_s = m.group(1), m.group(2)
        if resolve_board(name):
            days = int(days_s) if days_s is not None else None
            return render_board(name, days=days)
    first = text.split()[0].lstrip('/')
    if resolve_board(first) and len(text.split()) <= 2:
        days = None
        parts = text.split()
        if len(parts) == 2:
            try:
                days = int(parts[1])
            except ValueError:
                days = None
        return render_board(first, days=days)
    for pat, board in _NL_BOARD:
        if pat.search(text):
            return render_board(board)
    return None


def _looks_grounded(answer: str) -> bool:
    """Heuristic: refuse answers that look like invented market essays."""
    low = (answer or '').lower()
    if not answer or len(answer.strip()) < 8:
        return False
    if 'won’t invent' in low or "won't invent" in low or 'use a live vigil board' in low:
        return True
    # Banned hallucinated firm names from the bad Telegram session
    banned = (
        'ai infinitive', 'terranova secure', 'edgecore', 'overhiring by',
        'linkedin internal data', '60% higher conversion', '47,312',
    )
    if any(b in low for b in banned):
        return False
    # Require at least one digit from real tower stats style
    if _HIRING_INTENT.search(answer) and not re.search(r'\d', answer):
        return False
    return True


def ask_hermes(db: Session, prompt: str, *, force: bool = False) -> dict:
    text = (prompt or '').strip()
    if not text:
        return {'ok': False, 'allowed': False, 'answer': 'Ask a question about the tower.', 'queued': False}

    board_text = _try_board(text)
    if board_text is not None:
        return {
            'ok': True,
            'allowed': True,
            'queued': False,
            'board': True,
            'answer': board_text,
        }

    # Hiring free-form without a board match → hard refuse (no LLM invent path).
    # Live numbers only via /boards or NL phrases that map to render_board.
    if _HIRING_INTENT.search(text):
        return {
            'ok': True,
            'allowed': True,
            'queued': False,
            'board': False,
            'refused': True,
            'answer': REFUSE,
        }

    cap = compute_ai_capacity(db)
    if not cap['allowed'] and not force:
        _queue_prompt(text)
        wait = cap.get('cool_in_secs') or 60
        return {
            'ok': True,
            'allowed': False,
            'queued': True,
            'capacity': cap,
            'answer': (
                f'Tower busy collecting — Ask queued. '
                f'Try again in about {wait}s. ({cap["reason"]})'
            ),
        }

    if not HERMES_BIN.is_file():
        return {
            'ok': False,
            'allowed': True,
            'queued': False,
            'capacity': cap,
            'answer': 'Hermes is not installed. Use /towerinsights etc. for live boards.',
        }

    env = os.environ.copy()
    env['PATH'] = f"{Path.home() / '.local' / 'bin'}:{Path.home() / '.hermes' / 'bin'}:" + env.get('PATH', '')
    system_nudge = (
        'You are VIGIL. For any hiring/jobs/companies question, reply only with:\n'
        f'{REFUSE}\n'
        'Otherwise keep answers short. Never invent tower data.\n'
        f'Question: {text[:MAX_PROMPT]}'
    )
    try:
        proc = subprocess.run(
            [
                str(HERMES_BIN), 'chat',
                '-q', system_nudge,
                '-Q',
                '--max-turns', '2',
                '--provider', 'custom',
                '-m', 'qwen3.5:4b-hermes',
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            env=env,
            cwd=str(Path.home()),
        )
    except subprocess.TimeoutExpired:
        return {
            'ok': False,
            'allowed': True,
            'queued': False,
            'capacity': cap,
            'answer': 'Ask timed out. Use /towerinsights or /fresh for live boards.',
        }
    except Exception as e:
        return {
            'ok': False,
            'allowed': True,
            'queued': False,
            'capacity': cap,
            'answer': f'Ask failed to start Hermes: {e}',
        }

    out = (proc.stdout or '').strip()
    err = (proc.stderr or '').strip()
    lines = [ln for ln in out.splitlines() if not ln.startswith('session_id:')]
    answer = '\n'.join(lines).strip() or err or f'Hermes exited {proc.returncode}'
    if not _looks_grounded(answer) and _HIRING_INTENT.search(answer):
        answer = REFUSE

    return {
        'ok': proc.returncode == 0 and bool(answer),
        'allowed': True,
        'queued': False,
        'capacity': cap,
        'answer': answer[:8000],
        'exit_code': proc.returncode,
    }
