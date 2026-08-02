# Hermes Agent × Watch Tower (capacity-safe)

**Status:** Live on ThinkPad (2026-08-02)  
**Brain:** Local Ollama only — `qwen3.5:4b-hermes` (64k ctx)  
**Surfaces:** VIGIL Ask panel + Telegram-ready gateway + daily brief cron  

## Why Hermes

Hermes is the **chief intelligence officer** on top of Watch Tower data — not a second VIGIL, not a scrape replacement. It remembers Quanta context, talks via Telegram when wired, and answers Ask from live Ultron APIs through MCP.

## Capacity rule (non-negotiable)

| Priority | Who | When |
|---|---|---|
| 1 | LinkedIn scrape + title filter Ollama | Always wins |
| 2 | Hermes / VIGIL Ask | Only when `GET /api/ultron/ai-capacity` → `allowed: true` |

Blocked when: `ollama_live` **or** heat level `warm|hot|critical`.

This ThinkPad (RTX A3000 12GB, ~31GB RAM) **cannot** run always-on heavy Hermes chat *and* live Ollama filter at once. Time-slice or queue.

## Architecture

```
Telegram (optional) ──┐
VIGIL Ask panel ──────┼──► Hermes CLI (local) ──► Ollama 4b-hermes
                      │              │
                      │              └── MCP watch_tower ──► http://127.0.0.1:8001
System crontab 08:00 IST ──► hermes_daily_brief.py (no Ollama) ──► documents/briefs/
```

## Install layout (outside git)

| Path | Purpose |
|---|---|
| `~/.hermes/` | Hermes home (config, .env, skills, cron) |
| `~/.local/bin/hermes` | CLI |
| `~/.hermes/config.yaml` | Ollama custom provider + `mcp_servers.watch_tower` |
| `~/.hermes/SOUL.md` | Watch Tower personality |
| `hermes-gateway.service` | User systemd gateway (cron + messaging) |

## Repo pieces (in git)

| Path | Purpose |
|---|---|
| `job_engine/mcp/watch_tower_mcp.py` | Read-only MCP tools |
| `job_engine/app/ai_capacity.py` | Scrape-first mutex |
| `job_engine/app/hermes_ask.py` | Ask → Hermes subprocess |
| `job_engine/app/ultron/routes.py` | `/api/ultron/ai-capacity`, `/api/ultron/ask` |
| `job_engine/scripts/hermes_daily_brief.py` | Daily brief (HTTP only) |
| `job_engine/scripts/setup_hermes_telegram.sh` | Wire BotFather token |
| `job_engine/vigil` Ask panel | Canvas chat UI |

## MCP tools (read-only)

`ai_capacity`, `tower_health`, `tower_stats`, `hiring_signals`, `watchlist`, `top_companies`, `roles_rank`, `role_companies`, `search_jobs`

No write tools in v1 (no run scrape / toggle watch).

## Telegram setup (Ashok)

```bash
# 1) @BotFather → token
# 2) Get your numeric user id
TELEGRAM_BOT_TOKEN=xxxx TELEGRAM_ALLOWED_USERS=your_id \
  /home/user/Documents/job_engine/scripts/setup_hermes_telegram.sh

hermes gateway restart
# Point cron deliver at telegram when ready:
#   hermes cron edit 059dac98f0db   # set deliver telegram:CHAT_ID
```

Until then: briefs land in `documents/briefs/latest.txt` via system crontab `30 2 * * *` UTC (~08:00 IST) and Hermes cron `wt-mcp-brief` at 03:00 IST (agent + MCP when cool).

## Security quarantine

- Hermes installed with `--skip-browser` (no second Chromium vs LinkedIn)
- CLI toolsets limited (no terminal/browser by default in `platform_toolsets`)
- Never commit `~/.hermes/.env` or BotFather tokens
- Never point Hermes at LinkedIn Chrome profile / Postgres passwords

## Smoke checks

```bash
curl -s http://127.0.0.1:8001/api/ultron/ai-capacity | python3 -m json.tool
python3 job_engine/scripts/hermes_daily_brief.py | head
hermes chat -q "Reply HERMES_OK" -Q --max-turns 1 --provider custom
# VIGIL: open Ask panel → ask “Top hiring companies this week?”
```

## What we will not do

- Cloud Hermes brain (Ashok chose local Ollama)
- Hermes browser against LinkedIn
- Second large model always resident on the A3000
- Unattended write actions in v1
