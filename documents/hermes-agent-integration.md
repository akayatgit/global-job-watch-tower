# Hermes Agent × Watch Tower (capacity-safe)

**Status:** Live on ThinkPad (2026-08-02)  
**Brain:** Local Ollama only — `qwen3.5:4b-hermes` (64k ctx)  
**Surfaces:** VIGIL Ask panel + Telegram `@vigil_akay_bot` + daily brief cron  

## Hallucination fix (2026-08-02)

Early Telegram replies invented markets (fake “47k jobs”, “AI Infinitive”, etc.).
**Truth is Postgres via Ultron APIs.** Boards are now **deterministic text** — no LLM rewrite.

| Path | Role |
|---|---|
| `job_engine/app/vigil_boards.py` | Panel → plain text (same facts as VIGIL UI) |
| `job_engine/scripts/vigil_board.py` | CLI for Hermes `quick_commands` |
| `GET /api/ultron/boards/{name}` | Board JSON `{text:…}` |
| MCP `render_board` | Hermes must paste verbatim |
| `~/.hermes/config.yaml` `quick_commands` | `/towerinsights` etc. exec boards (bypass LLM) |

### Telegram slash boards

| Command | Board |
|---|---|
| `/towerinsights` | Tower Insights |
| `/health` | Tower health |
| `/hiringsignals` [days] | Hiring signals |
| `/searches` | Roles / searches |
| `/watchlist` | Watched companies |
| `/fresh` | Freshest catches |
| `/brief` | Daily hiring brief |
| `/carousel` | TECH JOB MARKET MOVEMENT — generate fiery 6-slide album via Replicate and send to this chat (Gate 1) |
| `/boards` | Help menu |

### DIRECTOR stack (2026-08-04) — OpenAI above Hermes

Named layers:

| Layer | Role |
|---|---|
| **COURIER** | Hermes Telegram inbox + send |
| **DIRECTOR** | OpenAI Agents SDK reasoner + skit + tool chooser |
| **STAGEHAND** | Ultron/Watch Tower fact APIs |
| **LENS** | Replicate `xai/grok-imagine-image` |
| **CAROUSEL WORKSHOP** | Multi-slide album workflow |

**Ingress 1A:** plugin `vigil-image-only` → `python -m app.director.router` → `skip` Ollama chat.

**Memory:** OpenAI Agents `SQLiteSession` at `job_engine/.data/director_sessions/director.db`  
`session_id = {bot}:{chat_id}` · `/new` `/reset` `/clear` wipe · different bot = fresh.

**Style:** TN Pinterest-2026 comic skit · limited on-image text · no Telegram essays.  
Package: [`job_engine/app/director/`](../job_engine/app/director/).

## Capacity rule (non-negotiable)

| Priority | Who | When |
|---|---|---|
| 1 | LinkedIn scrape + title filter Ollama | Always wins |
| 2 | Hermes free-form Ask | Only when `GET /api/ultron/ai-capacity` → `allowed: true` |

Board slash commands do **not** need Ollama (HTTP only).

## Architecture

```
Telegram /towerinsights ──► Hermes quick_command exec ──► vigil_board.py ──► Ultron API
Telegram free-form ───────► Hermes + MCP watch_tower ──► Ollama 4b (when cool)
VIGIL Ask panel ──────────► board shortcut OR Hermes (capacity-gated)
System crontab 08:00 IST ─► hermes_daily_brief.py ──► documents/briefs/ + send-brief
```

## Install layout (outside git)

| Path | Purpose |
|---|---|
| `~/.hermes/` | Hermes home (config, .env, skills, cron) |
| `~/.local/bin/hermes` | CLI |
| `~/.hermes/config.yaml` | Ollama + MCP + quick_commands + telegram toolsets |
| `~/.hermes/SOUL.md` | Anti-hallucination VIGIL personality |
| `hermes-gateway.service` | User systemd gateway |

## Repo pieces (in git)

| Path | Purpose |
|---|---|
| `job_engine/app/vigil_boards.py` | Board formatters |
| `job_engine/scripts/vigil_board.py` | Board CLI |
| `job_engine/mcp/watch_tower_mcp.py` | Read-only MCP + `render_board` |
| `job_engine/app/ai_capacity.py` | Scrape-first mutex |
| `job_engine/app/hermes_ask.py` | Ask → board shortcut or Hermes |
| `job_engine/scripts/hermes_daily_brief.py` | Daily brief (HTTP only) |
| `job_engine/scripts/telegram_watch_tower.py` | Bootstrap + send-brief + send-carousel |
| `job_engine/app/carousel_gen.py` | Replicate + Pillow carousel slides (ephemeral tmp) |
| `job_engine/scripts/carousel_fire.py` | Generate + Telegram album (`/carousel`) |

## MCP tools (read-only)

`ai_capacity`, `tower_health`, `tower_stats`, `hiring_signals`, `watchlist`,
`top_companies`, `roles_rank`, `role_companies`, `search_jobs`, `render_board`

## Telegram bot

- Bot: `@vigil_akay_bot`
- Token only in `~/.hermes/.env` (never git)
- Home chat linked via channel directory / bootstrap
- Crontab: brief then `telegram_watch_tower.py send-brief`

## Smoke checks

```bash
python3 job_engine/scripts/vigil_board.py towerinsights | head
python3 job_engine/scripts/vigil_board.py fresh | head
curl -s http://127.0.0.1:8001/api/ultron/boards/fresh | python3 -c "import sys,json;print(json.load(sys.stdin)['text'][:500])"
hermes gateway restart
# In Telegram: /towerinsights  /fresh  /health
```

## What we will not do

- Cloud Hermes brain (Ashok chose local Ollama)
- Hermes browser against LinkedIn
- LLM-authored hiring “intelligence” without MCP numbers
- Unattended write actions in v1
