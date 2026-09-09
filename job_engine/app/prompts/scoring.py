"""Hermes scoring — the local model reads a prompt and grades detail + flow.

Law: AI understands, it never authors the number alone. The final score is
a blend of the deterministic heuristic (structure/vocabulary that is
literally in the text) and the model's two rubric grades, and every model
reply passes a strict validator (fields, ranges, types) before it counts.
Proven winners from the RAG ride along as few-shot anchors so the grade is
relative to what already performed, not to the model's mood.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

AI_WEIGHT = 0.65
HEURISTIC_WEIGHT = 0.35
MAX_REASONS = 4
MAX_REASON_CHARS = 160
MAX_EXEMPLAR_CHARS = 900

RUBRIC = """You are the quality judge for AI video prompts used to recreate D2C product commercials (Veo, Kling, Sora).
Grade the CANDIDATE prompt on two axes, each 0-100:

DETAIL — how precisely it specifies the product (geometry, materials, branding to preserve), camera (lens, movement, framing), lighting, environment, duration/format, and constraints (what must not change).
FLOW — whether the shots read as one coherent cinematic sequence: clear start, motion that develops, a payoff/reveal, consistent tone, no contradictions, realistic for a 5-15 second clip.

{exemplar_block}
Return ONLY JSON:
{{"detail": <0-100 integer>, "flow": <0-100 integer>, "reasons": ["<short reason>", "<short reason>", "<short reason>"]}}
Reasons must quote or point at concrete parts of the candidate. Be strict: 85+ means a brand could shoot it tomorrow.

CANDIDATE:
\"\"\"{candidate}\"\"\"
"""

EXEMPLAR_HEADER = (
    'Calibration — these prompts already performed well for us '
    '(score they earned in brackets). Grade the candidate RELATIVE to them:\n'
)


@dataclass
class AIScore:
    detail: float
    flow: float
    reasons: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        return round((self.detail + self.flow) / 2.0, 1)


def build_prompt(candidate: str, exemplars: list[tuple[str, float]]) -> str:
    block = ''
    if exemplars:
        lines = [EXEMPLAR_HEADER]
        for index, (text, score) in enumerate(exemplars, 1):
            snippet = ' '.join((text or '').split())[:MAX_EXEMPLAR_CHARS]
            lines.append(f'[{index}] ({score:.0f}/100) {snippet}')
        block = '\n'.join(lines) + '\n'
    return RUBRIC.format(exemplar_block=block, candidate=(candidate or '')[:5000])


def validate_ai_reply(raw: str) -> AIScore | None:
    """Strict parse: both grades present, numeric, 0-100; reasons are short strings."""
    if not raw:
        return None
    text = str(raw)
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    grades: list[float] = []
    for key in ('detail', 'flow'):
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        value = float(value)
        if value < 0 or value > 100:
            return None
        grades.append(round(value, 1))
    reasons_raw = payload.get('reasons')
    reasons: list[str] = []
    if isinstance(reasons_raw, list):
        for item in reasons_raw:
            if isinstance(item, str):
                clean = ' '.join(item.split())
                if clean:
                    reasons.append(clean[:MAX_REASON_CHARS])
            if len(reasons) >= MAX_REASONS:
                break
    return AIScore(detail=grades[0], flow=grades[1], reasons=reasons)


def _chat(prompt: str) -> str:
    import ollama

    from app import config

    response = ollama.chat(
        model=config.OLLAMA_MODEL,
        messages=[{'role': 'user', 'content': prompt}],
        format='json',
        think=False,
        options={'temperature': 0, 'num_ctx': 8192, 'num_predict': 400},
    )
    return response['message']['content']


def ai_score(candidate: str, exemplars: list[tuple[str, float]], *, chat=None) -> AIScore | None:
    """Ask the local model (two attempts). None when AI is closed (heat) or
    the reply never validates — the caller keeps the heuristic only."""
    from app import config, thermal

    if getattr(config, 'AI_REQUIREMENTS_MODE', 'on') == 'off':
        return None
    if chat is None:
        if not thermal.ollama_path_open():
            return None
        chat = _chat
    prompt = build_prompt(candidate, exemplars)
    timeout = min(90.0, float(getattr(config, 'OLLAMA_TIMEOUT_S', 45.0)) * 1.5)
    for attempt in range(2):
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                raw = pool.submit(chat, prompt).result(timeout=timeout)
        except Exception as exc:
            logger.warning('prompt scoring failed (attempt %s): %s', attempt + 1, exc)
            continue
        parsed = validate_ai_reply(raw)
        if parsed is not None:
            return parsed
        logger.warning('prompt scoring reply failed validation (attempt %s)', attempt + 1)
    return None


def blend(heuristic: float, ai: AIScore | None) -> float:
    """Final 0-100. Without an AI grade the heuristic stands alone (capped
    at 70 so an unscored prompt can never outrank a judged one at the top)."""
    if ai is None:
        return round(min(70.0, float(heuristic)), 1)
    return round(HEURISTIC_WEIGHT * float(heuristic) + AI_WEIGHT * ai.score, 1)


def redact_for_log(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or ''))[:120]
