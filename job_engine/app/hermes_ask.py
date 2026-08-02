"""Bridge VIGIL Ask → Hermes CLI (local Ollama), capacity-gated."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai_capacity import compute_ai_capacity

HERMES_BIN = Path.home() / '.local' / 'bin' / 'hermes'
ASK_QUEUE = Path(__file__).resolve().parents[1] / '.data' / 'hermes_ask_queue.jsonl'
MAX_PROMPT = 4000
MAX_TURNS = 6
TIMEOUT_S = 180


def _queue_prompt(prompt: str) -> None:
    ASK_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    with ASK_QUEUE.open('a', encoding='utf-8') as f:
        f.write(json.dumps({
            'ts': time.time(),
            'prompt': prompt[:MAX_PROMPT],
        }) + '\n')


def ask_hermes(db: Session, prompt: str, *, force: bool = False) -> dict:
    text = (prompt or '').strip()
    if not text:
        return {'ok': False, 'allowed': False, 'answer': 'Ask a question about the tower.', 'queued': False}

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
            'answer': 'Hermes is not installed on this tower yet.',
        }

    env = os.environ.copy()
    env['PATH'] = f"{Path.home() / '.local' / 'bin'}:{Path.home() / '.hermes' / 'bin'}:" + env.get('PATH', '')
    # Keep Ask grounded
    system_nudge = (
        'You are Watch Tower Ask. Use watch-tower MCP tools for facts. '
        'Call ai_capacity first. Short plain-language answer. '
        f'Question: {text[:MAX_PROMPT]}'
    )
    try:
        proc = subprocess.run(
            [
                str(HERMES_BIN), 'chat',
                '-q', system_nudge,
                '-Q',
                '--max-turns', str(MAX_TURNS),
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
            'answer': 'Ask timed out — tower model is slow right now. Try a shorter question.',
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
    # Quiet mode prints session_id then answer — strip session lines
    lines = [ln for ln in out.splitlines() if not ln.startswith('session_id:')]
    answer = '\n'.join(lines).strip() or err or f'Hermes exited {proc.returncode}'
    return {
        'ok': proc.returncode == 0 and bool(answer),
        'allowed': True,
        'queued': False,
        'capacity': cap,
        'answer': answer[:8000],
        'exit_code': proc.returncode,
    }
