# Hermes Agent × Watch Tower (capacity-safe)

> **Telegram superseded by Gate 3.0 JobMaster (2026-08-04).** The historical
> Hermes/DIRECTOR architecture below remains for incident recovery and
> non-Telegram tools. Hermes no longer consumes Telegram updates. The dedicated
> `job_engine/scripts/telegram_job_bot.py` service is the only poller and routes
> every user through the same JobMaster capability layer: constrained language
> intent → live Watch Tower APIs → deterministic jobs/links/numbers/comparisons.
> Deployment fails if Hermes is still polling or JobMaster is unhealthy.

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

**Soul (2026-08-04):** DIRECTOR = Ashok’s **Jarvis** for the live job market.
Casual Telegram chat → visual discussion of tower/data (tiny punchy text in art).
Not a student bot, not PPT/poster ads. Prompts ≥ `MIN_PROMPT_CHARS`=800, invented
each turn. `read_vision_doc` for PRD/roadmap/ux/lead/hermes. Carousel = separate.
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
| `job_engine/app/carousel_gen.py` | Grok Imagine graphic carousel (text in art; ephemeral tmp) |
| `job_engine/app/prompt_dictionary.py` | `MIN_PROMPT_CHARS` + `GRAPHIC_STYLE_BRIEF` (tunable; no scene paste) |
| `job_engine/app/director/` | DIRECTOR agent + STAGEHAND/LENS/CAROUSEL/vision tools |
| `job_engine/scripts/carousel_fire.py` | Generate + Telegram album (`/carousel`) |

## MCP tools (read-only)

`ai_capacity`, `tower_health`, `tower_stats`, `hiring_signals`, `watchlist`,
`top_companies`, `roles_rank`, `role_companies`, `search_jobs`, `render_board`

## Telegram bot

- Bot: `@vigil_akay_bot`
- Token only in `~/.hermes/.env` (never git)
- Home chat linked via channel directory / bootstrap
- Crontab: brief then `telegram_watch_tower.py send-brief`

### Telegram guest access (2026-08-04)

**Incident:** Ashok tried to demo the bot to an investor from his phone — the
investor's messages (and his wife's, from a prior test) got zero replies.
Only Ashok's own linked account worked, and he had no ThinkPad terminal
access to fix it live. See `documents/kanban.md` card #1 for the full
incident writeup.

**Root cause:** Hermes' own Telegram connector enforces
`TELEGRAM_ALLOWED_USERS` **before** any plugin hook runs — a blocked
sender's message never reaches our code, so no repo-side fix could
intercept it. That gate lived entirely outside git, in `~/.hermes/.env`.

**Fix — our own allowlist replaces Hermes':**

1. **One-time manual step (ThinkPad terminal, do this once):** set
   `TELEGRAM_ALLOW_ALL_USERS=true` in `~/.hermes/.env` and restart the
   gateway (`hermes gateway restart`). `telegram_watch_tower.py bootstrap`
   now writes this by default for any future re-bootstrap. This is safe —
   every message now reaches our plugin hook, which enforces its own gate
   immediately below.
2. `job_engine/app/telegram_guests.py` — dependency-free (stdlib only) JSON
   store at `job_engine/.data/telegram_guests.json` (gitignored,
   ThinkPad-local): `{telegram_id: {expires_at, minutes, label, added_by}}`.
   The owner (Ashok — `TELEGRAM_ALLOWED_USERS` / `TELEGRAM_HOME_CHANNEL` in
   `~/.hermes/.env`) is always allowed and can never be revoked.
3. `job_engine/hermes_plugins/vigil-image-only/__init__.py`
   (`telegram_to_director`) checks `is_allowed(chat_id)` before dispatching
   to DIRECTOR. Unauthorised senders are dropped **silently** (matches the
   existing private-ops posture — the bot doesn't announce itself to
   randoms). The import is wrapped in a try/except that **fails open**
   (never blocks Ashok out over a bug in this module).
4. **Owner-only Telegram commands** (from Ashok's own chat, phone-only, no
   SSH/laptop/Cloudflare needed):
   - `/allow <telegram_id> [minutes=60] [label]` — grant temporary access by
     numeric id; also pings the guest directly so they know to go ahead.
   - `/revoke <telegram_id>` — remove numeric-id access immediately.
   - `/allowuser <telegram_username>` — grant **permanent** access by
     `@handle` (with or without the `@`), no numeric id lookup needed.
   - `/revokeuser <telegram_username>` — remove a granted `@handle`. Handles
     baked into `DEFAULT_ALLOWED_USERNAMES` (code, git-tracked) can't be
     revoked this way by design — pull them out of
     `job_engine/app/telegram_guests.py` and redeploy instead.
   - `/guests` — list allowed `@usernames` (default + granted) and active
     numeric-id guests with time remaining.
5. **Getting a guest's numeric Telegram id (only needed for `/allow`):**
   have them message [@userinfobot](https://t.me/userinfobot) once (doesn't
   touch our bot's state) and read their `Id` back to Ashok over any channel
   (voice, SMS, in person). Skip this entirely if you already know their
   `@username` — use `/allowuser` instead.

**Username allowlist (2026-08-04):** `job_engine/app/telegram_guests.py`
`DEFAULT_ALLOWED_USERNAMES` is a permanent, code-reviewed, git-tracked set —
no ThinkPad manual step, effective as soon as the deploy lands (unlike
numeric guests, which live only in the gitignored, ThinkPad-local
`telegram_guests.json`). Currently: `@azr0099`. Add a handle there whenever
Ashok says "allow telegram username @whoever", or use `/allowuser` from
Telegram for anything ad hoc that doesn't need a code change. Matching reads
the `username` Telegram attaches to the incoming sender (best-effort lookup
in `_sender_username()` in the plugin, since the exact Hermes connector
event shape isn't documented — falls back to "unknown" and the numeric-id
gate if it can't find one, never blocking the owner).

**Examples:**
- Ad hoc, live investor demo, no ThinkPad access:
  `/allow 987654321 60 investor demo` → their next message gets a real
  DIRECTOR reply → after 60 minutes it silently stops again → `/guests`
  shows the countdown → `/revoke 987654321` removes access immediately if
  needed sooner.
- Known handle, permanent: `/allowuser azr0099` (or bake it into
  `DEFAULT_ALLOWED_USERNAMES` for a code-reviewed, redeploy-proof grant) →
  every message from that `@username` gets a real reply, no expiry.

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
