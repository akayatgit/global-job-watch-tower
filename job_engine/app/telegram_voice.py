"""JobMaster voice layer — LLM warmth around deterministic facts, never
inside them.

Ashok's 1A decision (2026-08-05): the guest/customer conversation felt like
a rigid form ("we can't run on Regex... people want to naturally talk").
The fix: let an LLM rephrase tone, greetings, and connective language around
`JobMasterEngine`'s deterministic reply — but a byte-exact VALIDATOR (same
authenticity-gate pattern as `app/director/tools_validator.py`) guarantees
every job title, company, experience label, link, count, and comparison line
survives completely unmodified, in the same order. Any drift, timeout,
disabled flag, or missing key falls back to the untouched deterministic
reply — the guest never sees an unverified fact. This is an additive layer
on top of, not a replacement for, the deterministic engine: JobMasterEngine
and its existing contract-test suite stay pure and unaware this layer
exists.

Scope note (Ashok 2026-08-05): subscriptions/premium content are a later
phase and are NOT built here — but this layer is the seam that phase will
need (a place to speak naturally about an entitlement without regex ever
having to "understand" free-form marketing language). Kept generic — this
wraps any deterministic reply text, not only job listings — so future reply
kinds can reuse it unchanged.
"""

from __future__ import annotations

import os
import re

from app import config

URL_RE = re.compile(r'https?://\S+')

VOICE_SYSTEM_PROMPT = (
    "You are JobMaster's conversational voice for a Telegram chat. Rewrite "
    "the message below so it reads like a warm, natural, professional human "
    "reply instead of a rigid form or template. Hard rules, no exceptions:\n"
    "1. Every non-blank line of the original message that contains a job "
    "title, company, experience label, link, number, or comparison must "
    "appear in your output EXACTLY character-for-character, in the same "
    "order — copy those lines verbatim, do not paraphrase or reformat them.\n"
    "2. Never add a job, company, link, number, comparison, or claim that "
    "is not already in the original message. Never invent facts.\n"
    "3. You may add short natural connective, greeting, or encouraging "
    "sentences before, between, or after those exact lines.\n"
    "4. No emojis, no sales pressure, no filler disclaimers. Keep it "
    "concise and Telegram-appropriate.\n"
    "Return only the rewritten message, nothing else — no preamble."
)


def _fact_lines(text: str) -> list[str]:
    return [line for line in (text or '').split('\n') if line.strip()]


def validate_voice(original: str, candidate: str) -> bool:
    """Fact-lock gate: every non-blank line of `original` must reappear
    verbatim, in order, inside `candidate`, and `candidate` may not
    introduce a URL absent from `original`.

    Deliberately strict — the model may only add text around facts, never
    touch the facts themselves. A false rejection just falls back to the
    safe deterministic reply (life is lost, nothing else); a false approval
    would leak an altered fact, which this design treats as unacceptable.
    """
    candidate = (candidate or '').strip()
    if not candidate:
        return False
    cursor = 0
    for line in _fact_lines(original):
        idx = candidate.find(line, cursor)
        if idx == -1:
            return False
        cursor = idx + len(line)
    original_urls = set(URL_RE.findall(original or ''))
    candidate_urls = set(URL_RE.findall(candidate))
    if candidate_urls - original_urls:
        return False
    return True


class VoiceLayer:
    """Best-effort warmth pass with a hard authenticity fallback.

    `client_factory` lets tests inject a stub OpenAI client without touching
    real credentials; production code leaves it unset and gets a real
    `openai.OpenAI` client built from `app.config`.
    """

    def __init__(self, *, enabled: bool | None = None, client_factory=None):
        if enabled is None:
            enabled = os.getenv('JOBMASTER_VOICE_LLM', 'true').strip().lower() == 'true'
        self.enabled = bool(enabled) and bool(config.OPENAI_API_KEY)
        self._client_factory = client_factory

    def _client(self):
        if self._client_factory is not None:
            return self._client_factory()
        from openai import OpenAI

        return OpenAI(api_key=config.OPENAI_API_KEY, timeout=8)

    def speak(self, reply: str) -> str:
        """Return a warmer rewrite of `reply`, or `reply` itself untouched
        whenever the layer is disabled, the model call fails/times out, or
        the fact-lock validator rejects the candidate."""
        text = (reply or '').strip()
        if not self.enabled or not text:
            return reply
        try:
            client = self._client()
            response = client.chat.completions.create(
                model=config.OPENAI_BRAIN_MODEL,
                temperature=0.5,
                messages=[
                    {'role': 'system', 'content': VOICE_SYSTEM_PROMPT},
                    {'role': 'user', 'content': text[:3500]},
                ],
            )
            candidate = (response.choices[0].message.content or '').strip()
        except Exception:
            return reply
        return candidate if validate_voice(text, candidate) else reply
