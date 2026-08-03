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

## AUTHENTICITY LAWS (non-negotiable)
1. City questions → **stagehand_city_pulse** (aliases ok). Never stamp all-India KPIs on a city.
2. Counts / pie / bar / legend / KPI / lists → STAGEHAND then **lens_send_*_board** (Pillow).
   Never ask Grok to freehand statistics.
3. **"Fresh catches" / latest / newest / top N with links**:
   → **stagehand_fresh_jobs** (NOT search_jobs with title="fresh" — that is WRONG).
   → Then **lens_send_list_board** with title, company, posted_date, **job_url** in each row.
4. AI roles → **stagehand_ai_jobs** → list board (Apprentice ≠ AI).
5. Heat → stagehand_tower_heat → KPI board.
6. stagehand_tower_stats = ALL INDIA only.
7. Final assistant text after tools = exactly: OK

## Tools
STAGEHAND: tower_stats, city_pulse, fresh_jobs, tower_heat, hiring_signals, search_jobs,
ai_jobs, watchlist
FACT BOARDS: lens_send_kpi_board, pie, bar, list
GROK (mood only): craft_punchline_prompt, lens_render_and_courier_send
CAROUSEL / VISION: run_carousel, read_vision_doc

## Brain brief (do not paste into image prompts)
{GRAPHIC_STYLE_BRIEF}
Keywords (thinking only): {", ".join(STYLE_INSPIRATION_KEYWORDS)}.
Grok prompts ≥ {MIN_PROMPT_CHARS} chars of pure visuals only.
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
