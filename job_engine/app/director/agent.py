"""DIRECTOR — OpenAI Agents SDK orchestrator."""

from __future__ import annotations

import os

from agents import Agent, ModelSettings, Runner

from app import config
from app.director.sessions import get_session
from app.director.tools_carousel import run_carousel
from app.director.tools_lens import craft_skit_frame, lens_render_and_courier_send
from app.director.tools_stagehand import (
    stagehand_hiring_signals,
    stagehand_search_jobs,
    stagehand_tower_stats,
    stagehand_watchlist,
)

DIRECTOR_INSTRUCTIONS = """
You are DIRECTOR for JobMaster / Global Job WATCH TOWER (Quanta HR).
Ashok talks on Telegram via COURIER. You MUST deliver every reply as an IMAGE tool call.
Never finish with a long text answer. Final spoken output = OK only.

## Layers
- DIRECTOR = you
- STAGEHAND = fact tools (call before numbers)
- LENS/COURIER = craft_skit_frame then lens_render_and_courier_send
- CAROUSEL WORKSHOP = run_carousel when user says Carousel / wants album

## Style
Tamil Nadu skit beats · Pinterest 2026 comics · limited on-image text (1–2 short lines) · bright · helpful.

## Mandatory tool sequence (every turn except pure /new handled outside you)
1) Call STAGEHAND if you need facts (greetings still call stagehand_tower_stats for a live pulse).
2) If Carousel intent → run_carousel once and stop.
3) Else → craft_skit_frame → lens_render_and_courier_send.
4) Then reply with exactly: OK
"""


def build_director() -> Agent:
    if config.OPENAI_API_KEY:
        os.environ['OPENAI_API_KEY'] = config.OPENAI_API_KEY
    return Agent(
        name='DIRECTOR',
        instructions=DIRECTOR_INSTRUCTIONS,
        model=config.OPENAI_BRAIN_MODEL or 'gpt-4.1-mini',
        model_settings=ModelSettings(tool_choice='required'),
        tools=[
            stagehand_tower_stats,
            stagehand_hiring_signals,
            stagehand_search_jobs,
            stagehand_watchlist,
            craft_skit_frame,
            lens_render_and_courier_send,
            run_carousel,
        ],
    )


def run_director(text: str, *, bot: str, chat_id: str) -> str:
    """Run one DIRECTOR turn with persistent SQLiteSession memory."""
    if config.OPENAI_API_KEY:
        os.environ['OPENAI_API_KEY'] = config.OPENAI_API_KEY
    agent = build_director()
    session = get_session(bot, chat_id)
    result = Runner.run_sync(agent, text, session=session, max_turns=12)
    return (result.final_output or '').strip()
