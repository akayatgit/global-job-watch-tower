"""DIRECTOR workflow traces — full audit from Telegram message → tools → send."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from agents import RunHooks

from app import config

TZ = ZoneInfo('Asia/Kolkata')
TRACE_DIR = config.BASE_DIR / '.data' / 'director_traces'
_lock = threading.Lock()
_CURRENT: 'DirectorTrace | None' = None


def _now() -> str:
    return datetime.now(TZ).isoformat()


def _clip(val: Any, limit: int = 8000) -> Any:
    if val is None:
        return None
    if isinstance(val, (str, int, float, bool)):
        s = str(val)
        return s if len(s) <= limit else s[:limit] + f'…[+{len(s) - limit} chars]'
    # Force JSON-safe via default=str (OpenAI SDK objects etc.)
    try:
        s = json.dumps(val, ensure_ascii=False, default=str)
    except Exception:
        s = repr(val)
    if len(s) <= limit:
        try:
            return json.loads(s)
        except Exception:
            return s
    return {'_truncated': True, 'preview': s[:limit], 'chars': len(s)}


class DirectorTrace:
    def __init__(self, *, bot: str, chat: str, text: str):
        self.id = datetime.now(TZ).strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
        self.data: dict[str, Any] = {
            'id': self.id,
            'started_at': _now(),
            'finished_at': None,
            'bot': bot,
            'chat': chat,
            'user_text': text,
            'status': 'running',
            'attempts': [],
            'nodes': [],
            'outcome': None,
            'loophole_hints': [],
        }

    def node(self, kind: str, **payload: Any) -> None:
        self.data['nodes'].append({
            'ts': _now(),
            'kind': kind,
            **{k: _clip(v) for k, v in payload.items()},
        })
        self._flush()

    def hint(self, msg: str) -> None:
        self.data['loophole_hints'].append({'ts': _now(), 'hint': msg})
        self._flush()

    def finish(self, status: str, outcome: dict | None = None) -> None:
        self.data['status'] = status
        self.data['finished_at'] = _now()
        if outcome:
            self.data['outcome'] = _clip(outcome, 4000)
        self._flush()

    def _flush(self) -> None:
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        path = TRACE_DIR / f'{self.id}.json'
        with _lock:
            path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2, default=str),
                encoding='utf-8',
            )
            # maintain slim index
            idx_path = TRACE_DIR / 'index.json'
            rows = []
            if idx_path.exists():
                try:
                    rows = json.loads(idx_path.read_text(encoding='utf-8'))
                except Exception:
                    rows = []
            summary = {
                'id': self.id,
                'started_at': self.data['started_at'],
                'finished_at': self.data.get('finished_at'),
                'status': self.data.get('status'),
                'user_text': (self.data.get('user_text') or '')[:160],
                'bot': self.data.get('bot'),
                'chat': self.data.get('chat'),
                'node_count': len(self.data.get('nodes') or []),
                'hints': len(self.data.get('loophole_hints') or []),
                'outcome_kind': (self.data.get('outcome') or {}).get('kind')
                if isinstance(self.data.get('outcome'), dict) else None,
            }
            rows = [r for r in rows if r.get('id') != self.id]
            rows.insert(0, summary)
            idx_path.write_text(
                json.dumps(rows[:200], ensure_ascii=False, indent=2, default=str),
                encoding='utf-8',
            )

def start_trace(*, bot: str, chat: str, text: str) -> DirectorTrace:
    global _CURRENT
    tr = DirectorTrace(bot=bot, chat=chat, text=text)
    tr.node('courier_receive', platform='telegram', text=text)
    _CURRENT = tr
    return tr


def current_trace() -> DirectorTrace | None:
    return _CURRENT


def clear_current() -> None:
    global _CURRENT
    _CURRENT = None


def list_traces(limit: int = 40) -> list[dict]:
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    idx = TRACE_DIR / 'index.json'
    if not idx.exists():
        return []
    try:
        rows = json.loads(idx.read_text(encoding='utf-8'))
    except Exception:
        return []
    return rows[:limit]


def get_trace(trace_id: str) -> dict | None:
    path = TRACE_DIR / f'{trace_id}.json'
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


class DirectorRunHooks(RunHooks):
    """Capture LLM + tool nodes for the active DIRECTOR trace."""

    def __init__(self, trace: DirectorTrace, *, attempt: int):
        self.trace = trace
        self.attempt = attempt

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        self.trace.node(
            'openai_llm_start',
            attempt=self.attempt,
            agent=getattr(agent, 'name', 'DIRECTOR'),
            system_prompt=system_prompt,
            input_items=input_items,
        )

    async def on_llm_end(self, context, agent, response) -> None:
        usage = str(getattr(response, 'usage', ''))[:500]
        output_preview = ''
        try:
            output_preview = str(getattr(response, 'output', response))[:2000]
        except Exception:
            output_preview = ''
        self.trace.node(
            'openai_llm_end',
            attempt=self.attempt,
            usage=usage,
            output_preview=output_preview,
        )

    async def on_tool_start(self, context, agent, tool) -> None:
        name = getattr(tool, 'name', None) or getattr(tool, '__name__', str(tool))
        args = getattr(context, 'tool_arguments', None)
        call_id = getattr(context, 'tool_call_id', None)
        self.trace.node(
            'tool_start',
            attempt=self.attempt,
            tool=name,
            call_id=call_id,
            arguments=args,
        )
        # Detect dumb literal "fresh" title search
        try:
            raw = args if isinstance(args, str) else json.dumps(args or {})
            if '"title"' in raw and '"fresh"' in raw.lower():
                self.trace.hint(
                    'TOOL LOOPHOLE: searched title="fresh" for "fresh catches" — '
                    'should use stagehand_fresh_jobs / scraped_at order, not keyword fresh'
                )
        except Exception:
            pass

    async def on_tool_end(self, context, agent, tool, result) -> None:
        name = getattr(tool, 'name', None) or getattr(tool, '__name__', str(tool))
        call_id = getattr(context, 'tool_call_id', None)
        self.trace.node(
            'tool_end',
            attempt=self.attempt,
            tool=name,
            call_id=call_id,
            result=result,
        )

    async def on_agent_end(self, context, agent, output) -> None:
        self.trace.node(
            'agent_end',
            attempt=self.attempt,
            final_output=output,
        )
        if output and str(output).strip() not in ('OK', 'ok') and len(str(output).strip()) > 8:
            self.trace.hint(
                'AGENT LOOPHOLE: final text was not OK — DIRECTOR may have essayed instead of board-only'
            )
