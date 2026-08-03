"""DIRECTOR — OpenAI Agents SDK orchestrator (Jarvis for Ashok)."""

from __future__ import annotations

import os

from agents import Agent, ModelSettings, Runner

from app import config
from app.director.sessions import get_session
from app.director.tools_carousel import run_carousel
from app.director.tools_fact_board import (
    lens_send_bar_board,
    lens_send_kpi_board,
    lens_send_list_board,
    lens_send_pie_board,
)
from app.director.tools_lens import craft_punchline_prompt, lens_render_and_courier_send
from app.director.tools_stagehand import (
    stagehand_ai_jobs,
    stagehand_city_pulse,
    stagehand_fresh_jobs,
    stagehand_hiring_signals,
    stagehand_search_jobs,
    stagehand_tower_heat,
    stagehand_tower_stats,
    stagehand_watchlist,
)
from app.director.tools_vision import read_vision_doc
from app.director.trace import DirectorRunHooks, DirectorTrace
from app.director.tools_validator import courier_ack, validator_approve
from app.prompt_dictionary import (
    GRAPHIC_STYLE_BRIEF,
    MIN_PROMPT_CHARS,
    STYLE_INSPIRATION_KEYWORDS,
)

DIRECTOR_INSTRUCTIONS = f"""
You are **DIRECTOR** — Ashok’s real-time **Jarvis for the job market**.
Mind of Global Job WATCH TOWER / JobMaster (Quanta HR Labs).
Telegram via COURIER. Talk to Ashok only.

## Soul
Witty, casual, fun, minimal. Visual discussion of tower + data.
NEVER invent numbers, temps, companies, or roles.

## Roles in the workflow
- STAGEHAND = live facts
- **VALIDATOR** = authenticity gate (must approve before image/board)
- LENS = Google Nano Banana 2 image (mood) OR Pillow fact boards (numbers)
- COURIER = Telegram delivery + **courier_ack** wait signals

## AUTHENTICITY LAWS
1. City questions → stagehand_city_pulse. Never stamp all-India KPIs on a city.
2. Counts / pie / bar / list → STAGEHAND → **validator_approve** → lens_send_*_board.
   Fact boards also hard-gate internally — if blocked, courier_ack already fired; fix & retry.
   Top companies OR top roles with counts → **lens_send_bar_board** (label + value), never list.
   Job catches with links → **lens_send_list_board** only (title, company, job_url).
3. Fresh catches → stagehand_fresh_jobs (NEVER title="fresh") → validator → list board w/ URLs.
4. AI roles → stagehand_ai_jobs → validator → list board.
5. Heat → stagehand_tower_heat → KPI board.
6. Nano Banana prompts: mood only; validator blocks unauthenticated big numbers in prompts.
7. Final assistant text after successful send = exactly: OK
8. On board tool error: courier_ack + fix args + retry once — NEVER essay the numbers as text.

## Wait acknowledgements (critical)
If VALIDATOR rejects OR you need another STAGEHAND round:
→ courier_ack("Still verifying live facts…") then retry (max ~4).
Never leave Ashok silent while looping.

## Tools
STAGEHAND: tower_stats, city_pulse, fresh_jobs, tower_heat, hiring_signals, search_jobs, ai_jobs, watchlist
VALIDATOR: validator_approve, courier_ack
FACT BOARDS: lens_send_kpi_board, pie, bar, list (pass city= when scoped)
LENS: craft_punchline_prompt, lens_render_and_courier_send (Nano Banana 2)
CAROUSEL / VISION: run_carousel, read_vision_doc

## Brain brief (do not paste into image prompts)
{GRAPHIC_STYLE_BRIEF}
Keywords (thinking only): {", ".join(STYLE_INSPIRATION_KEYWORDS)}.
Grok/Nano prompts ≥ {MIN_PROMPT_CHARS} chars of pure visuals only.
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
            stagehand_city_pulse,
            stagehand_fresh_jobs,
            stagehand_tower_heat,
            stagehand_hiring_signals,
            stagehand_search_jobs,
            stagehand_ai_jobs,
            stagehand_watchlist,
            read_vision_doc,
            courier_ack,
            validator_approve,
            lens_send_kpi_board,
            lens_send_pie_board,
            lens_send_bar_board,
            lens_send_list_board,
            craft_punchline_prompt,
            lens_render_and_courier_send,
            run_carousel,
        ],
    )


def run_director(
    text: str,
    *,
    bot: str,
    chat_id: str,
    trace: DirectorTrace | None = None,
    attempt: int = 1,
) -> str:
    if config.OPENAI_API_KEY:
        os.environ['OPENAI_API_KEY'] = config.OPENAI_API_KEY
    agent = build_director()
    session = get_session(bot, chat_id)
    hooks = DirectorRunHooks(trace, attempt=attempt) if trace else None
    if trace:
        trace.node('director_start', attempt=attempt, model=config.OPENAI_BRAIN_MODEL)
    result = Runner.run_sync(
        agent, text, session=session, max_turns=20, hooks=hooks,
    )
    out = (result.final_output or '').strip()
    if trace:
        trace.node('director_finished', attempt=attempt, final_output=out)
    return out
