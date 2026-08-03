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
    stagehand_hiring_signals,
    stagehand_search_jobs,
    stagehand_tower_heat,
    stagehand_tower_stats,
    stagehand_watchlist,
)
from app.director.tools_vision import read_vision_doc
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
1. City questions (Bangalore / Bengaluru / Chennai / …):
   → **stagehand_city_pulse** (or city-scoped signals/search).
   → NEVER slap all-India `jobs_today` / `companies` onto a city label.
2. Any **count, pie, bar, legend, KPI, list of jobs**:
   → Pull STAGEHAND facts → send with **lens_send_*_board** (Pillow).
   → Do **NOT** ask Grok/LENS to freehand a chart with numbers.
3. AI roles asks:
   → **stagehand_ai_jobs** (strict titles; Apprentice ≠ AI) → **lens_send_list_board**.
4. Heat / temp → stagehand_tower_heat → fact board or short visual OK.
5. stagehand_tower_stats = ALL INDIA only. Label it all-India if used.
6. Final assistant text after tools = exactly: OK

## Tools
STAGEHAND: tower_stats, city_pulse, tower_heat, hiring_signals(city=), search_jobs,
ai_jobs, watchlist
FACT BOARDS (trusted numbers): lens_send_kpi_board, lens_send_pie_board,
lens_send_bar_board, lens_send_list_board
GROK LENS (mood only — no hard stats): craft_punchline_prompt, lens_render_and_courier_send
CAROUSEL: run_carousel when Ashok says Carousel
VISION: read_vision_doc

## When to use Grok vs fact boards
- Pie / bar / legend / “how many” / city totals / job lists → **fact boards**
- Casual vibe with no critical numbers → Grok OK (still no fake stats in the prompt)

## Brain brief (do not paste into image prompts)
{GRAPHIC_STYLE_BRIEF}
Keywords (thinking only): {", ".join(STYLE_INSPIRATION_KEYWORDS)}.
If using Grok: pure visual prompt ≥ {MIN_PROMPT_CHARS} chars, no policy essay paste.
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


def run_director(text: str, *, bot: str, chat_id: str) -> str:
    if config.OPENAI_API_KEY:
        os.environ['OPENAI_API_KEY'] = config.OPENAI_API_KEY
    agent = build_director()
    session = get_session(bot, chat_id)
    result = Runner.run_sync(agent, text, session=session, max_turns=20)
    return (result.final_output or '').strip()
