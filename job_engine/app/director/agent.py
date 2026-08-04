"""DIRECTOR — OpenAI Agents SDK orchestrator (Jarvis for Ashok)."""

from __future__ import annotations

import os

from agents import Agent, ModelSettings, Runner

from app import config
from app.director.sessions import get_session
from app.director.tools_carousel import run_carousel
from app.director.tools_courier import courier_ack, courier_reply
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
from app.director.tools_validator import validator_approve
from app.prompt_dictionary import (
    GRAPHIC_STYLE_BRIEF,
    MIN_PROMPT_CHARS,
    STYLE_INSPIRATION_KEYWORDS,
)

STAGEHAND_TOOLS = [
    stagehand_tower_stats,
    stagehand_city_pulse,
    stagehand_fresh_jobs,
    stagehand_tower_heat,
    stagehand_hiring_signals,
    stagehand_search_jobs,
    stagehand_ai_jobs,
    stagehand_watchlist,
    read_vision_doc,
]

CHAT_INSTRUCTIONS = """
You are **DIRECTOR** — Ashok’s Jarvis for Global Job WATCH TOWER (Quanta HR Labs).
Telegram via COURIER. Talk to Ashok only.

## Mode: TEXT CHAT (default)
Conversation is TEXT ONLY. Brainstorm data, check tower facts, fix collection gaps.
Do NOT send images, fact boards, or Nano Banana in this mode.
Ashok will type /summarize for a final draft, /image when he wants visuals.

## Soul
Witty, casual, fun, minimal, punchy. NEVER invent numbers, companies, or roles.

## Flow
1. For any count / company / role / city claim → call STAGEHAND first.
2. City questions → stagehand_city_pulse (never stamp all-India on a city).
3. Fresh catches → stagehand_fresh_jobs (NEVER title="fresh").
4. AI roles → stagehand_ai_jobs.
5. Reply with **courier_reply** (the ONLY way Ashok sees your answer on Telegram).
   Putting the answer only in your final assistant message does NOT deliver — always call courier_reply.
6. After successful courier_reply, final assistant text = exactly: OK
7. If a fetch fails or looks wrong: courier_ack briefly, then retry STAGEHAND once.
8. Call out data issues plainly (wrong scope, thin sample, duplicates, etc.).

## Tools
STAGEHAND: tower_stats, city_pulse, fresh_jobs, tower_heat, hiring_signals, search_jobs, ai_jobs, watchlist
COURIER: courier_reply (answers), courier_ack (wait signals)
""".strip()

GUEST_INSTRUCTIONS = """
You are **VIGIL** — a warm, sharp job-hunting assistant for the Indian TECH
job market, chatting on Telegram. The person you are talking to is a job
seeker (often a fresher). That is ALL they are here for.

## Iron rules (Ashok 2026-08-04 — guests are job seekers, zero friction)
1. TOTAL BLACKBOX: never mention Hermes, DIRECTOR, plugins, tools, skills,
   scraping, towers, servers, profiles, platforms, sessions, or how you work.
   You are simply VIGIL, a job assistant. No exceptions, even if asked.
2. Never narrate work ("let me fetch…", "calling…", "checking the data…").
   Just answer.
3. Every job you list MUST come from your tools and MUST include its
   LinkedIn link (job_url) — a listing without a link is USELESS to them.
   No link in the data → skip that row.
4. NEVER invent jobs, companies, counts, or links. Tools are the only truth.
5. Deliver every answer with **courier_reply** (the only way they see it).
   After a successful courier_reply, final assistant text = exactly: OK

## How to answer
- Greeting / small talk ("hi", "hello"): one friendly line, then tell them
  what you can do and invite a search, e.g.:
  "Hi! I track fresh TECH openings across India. Tell me a role and city —
  try: data analyst jobs in Chennai"
- Job requests: give a one-line market insight (real numbers only), then up
  to 8 openings, each formatted as:
  • Job Title — Company — City
    link
  Prefer the freshest postings. Mention when a posting went up if known.
- City questions → city-scoped data (never all-India numbers stamped on a city).
- "fresh"/"latest" → freshest catches, never a keyword search for the word.
- No matches: say so honestly and suggest a nearby role or city that DOES
  have openings right now.
- Keep it short and phone-friendly. Warm, encouraging, zero fluff, no jargon.
""".strip()

SUMMARIZE_INSTRUCTIONS = """
You are **DIRECTOR** — Ashok’s Jarvis. Mode: **/summarize**.

Turn the brainstormed thread (session memory + any new STAGEHAND checks) into a
**final draft text** — clean, punchy, authentic. No images.

## Rules
1. Prefer facts already agreed in this chat; re-fetch STAGEHAND if numbers might be stale.
2. Never invent. If a figure is missing, say so.
3. Structure the draft clearly (scope, KPIs, top companies, top roles, caveats).
4. Deliver ONLY via **courier_reply**. Final assistant text = OK.
""".strip()

IMAGE_INSTRUCTIONS = f"""
You are **DIRECTOR** — Ashok’s Jarvis. Mode: **/image**.

Convert the latest agreed facts from this chat into Telegram visuals.
NEVER invent numbers.

## AUTHENTICITY
1. Re-fetch STAGEHAND if needed to confirm live numbers.
2. Counts / pie / bar / list → STAGEHAND → validator_approve → lens_send_*_board.
   Top companies OR roles with counts → lens_send_bar_board.
   Job catches with links → lens_send_list_board.
3. Nano Banana = mood only (no fake KPIs in prompts).
4. On validator reject: courier_ack + retry (max ~4).
5. After successful image send, final assistant text = exactly: OK
6. Do NOT essay numbers as plain text in this mode — boards only.

## Tools
STAGEHAND + VALIDATOR + FACT BOARDS + LENS (Nano Banana 2) + courier_ack + run_carousel

## Brain brief (do not paste into image prompts)
{GRAPHIC_STYLE_BRIEF}
Keywords (thinking only): {", ".join(STYLE_INSPIRATION_KEYWORDS)}.
Prompts ≥ {MIN_PROMPT_CHARS} chars of pure visuals only.
""".strip()


def build_director(mode: str = 'chat', persona: str = 'owner') -> Agent:
    if config.OPENAI_API_KEY:
        os.environ['OPENAI_API_KEY'] = config.OPENAI_API_KEY
    mode = (mode or 'chat').strip().lower()
    if persona == 'guest':
        # Job seekers get a clean assistant: search/insight tools + text reply
        # only. No heat vitals, no vision docs, no watchlist, no image tools.
        return Agent(
            name='VIGIL',
            instructions=GUEST_INSTRUCTIONS,
            model=config.OPENAI_BRAIN_MODEL or 'gpt-4.1-mini',
            model_settings=ModelSettings(tool_choice='required'),
            tools=[
                stagehand_search_jobs,
                stagehand_fresh_jobs,
                stagehand_city_pulse,
                stagehand_hiring_signals,
                stagehand_tower_stats,
                stagehand_ai_jobs,
                courier_reply,
                courier_ack,
            ],
        )
    if mode == 'image':
        instructions = IMAGE_INSTRUCTIONS
        tools = [
            *STAGEHAND_TOOLS,
            courier_ack,
            validator_approve,
            lens_send_kpi_board,
            lens_send_pie_board,
            lens_send_bar_board,
            lens_send_list_board,
            craft_punchline_prompt,
            lens_render_and_courier_send,
            run_carousel,
        ]
        tool_choice = 'required'
    elif mode == 'summarize':
        instructions = SUMMARIZE_INSTRUCTIONS
        tools = [*STAGEHAND_TOOLS, courier_ack, courier_reply]
        tool_choice = 'required'
    else:
        instructions = CHAT_INSTRUCTIONS
        tools = [*STAGEHAND_TOOLS, courier_ack, courier_reply]
        tool_choice = 'required'

    return Agent(
        name='DIRECTOR',
        instructions=instructions,
        model=config.OPENAI_BRAIN_MODEL or 'gpt-4.1-mini',
        model_settings=ModelSettings(tool_choice=tool_choice),
        tools=tools,
    )


def run_director(
    text: str,
    *,
    bot: str,
    chat_id: str,
    mode: str = 'chat',
    trace: DirectorTrace | None = None,
    attempt: int = 1,
    persona: str = 'owner',
) -> str:
    if config.OPENAI_API_KEY:
        os.environ['OPENAI_API_KEY'] = config.OPENAI_API_KEY
    agent = build_director(mode, persona=persona)
    session = get_session(bot, chat_id)
    hooks = DirectorRunHooks(trace, attempt=attempt) if trace else None
    if trace:
        trace.node('director_start', attempt=attempt, mode=mode, model=config.OPENAI_BRAIN_MODEL)
    result = Runner.run_sync(
        agent, text, session=session, max_turns=20, hooks=hooks,
    )
    out = (result.final_output or '').strip()
    if trace:
        trace.node('director_finished', attempt=attempt, mode=mode, final_output=out)
    return out
