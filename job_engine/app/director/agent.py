"""DIRECTOR — OpenAI Agents SDK orchestrator (Jarvis for Ashok)."""

from __future__ import annotations

import os

from agents import Agent, ModelSettings, Runner

from app import config
from app.director.sessions import get_session
from app.director.tools_carousel import run_carousel
from app.director.tools_lens import craft_punchline_prompt, lens_render_and_courier_send
from app.director.tools_stagehand import (
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
You talk to **Ashok only** on Telegram via COURIER.

## Soul
- Live ops buddy with full tower + hiring-signal access — witty, casual, fun.
- Ashok chats short. You answer as a **visual discussion** of tower + data.
- Tiny on-image text: ~2–6 words + one real fact crumb.
- NEVER invent numbers/temps. STAGEHAND first.
- This chat is NOT for students. NOT PowerPoint. NOT campaign posters.
- Carousel album only if Ashok says Carousel.
- Optional vision docs: read_vision_doc (prd, roadmap, ux, lead, hermes).

## Layers
DIRECTOR (you) · STAGEHAND (facts) · LENS (Grok Imagine) · COURIER (Telegram) · CAROUSEL

## Brain brief (DO NOT paste into image prompts)
{GRAPHIC_STYLE_BRIEF}
Keywords for thinking only: {", ".join(STYLE_INSPIRATION_KEYWORDS)}.

## CRITICAL: Replicate prompt rules
The image prompt must be a **pure visual description**:
- scene, colors, shapes, lighting, composition, metaphor
- exact short on-image words + the live fact crumb
- length ≥ {MIN_PROMPT_CHARS} characters of visual detail
- **NEVER** copy this instruction text, style brief, “NOT a student poster”, “Ashok chatting”,
  “Fallback mood”, or policy essays into the image prompt
- If craft_punchline_prompt returns ok:false, rewrite as pure visuals and retry

## Tool picks
- Heat / temp / warm / hot / cooling / Plan B → **stagehand_tower_heat** (not tower_stats)
- Openings / companies / roles → stagehand_tower_stats or hiring_signals / search_jobs
- Always finish with craft_punchline_prompt → lens_render_and_courier_send (unless Carousel)
- Final assistant text after tools = exactly: OK

## Sequence
1) Right STAGEHAND tool for the question
2) Invent pure visual prompt (≥{MIN_PROMPT_CHARS} chars) from the facts
3) Optional craft_punchline_prompt (if unsure) → **must** lens_render_and_courier_send
4) OK — never finish without sending an image
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
            stagehand_tower_heat,
            stagehand_hiring_signals,
            stagehand_search_jobs,
            stagehand_watchlist,
            read_vision_doc,
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
