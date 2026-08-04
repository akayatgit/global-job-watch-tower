# Milestone — Eureka: the Job Telegram AI Bot (recover here)

| Field | Value |
|---|---|
| Date | 2026-08-04 |
| Label | `milestone/eureka-telegram-bot` |
| Intent | Ashok's own words: **"Eureka, we created a Job Telegram AI Bot."** First working, live Telegram surface for Global Job WATCH TOWER — talk to the tower from a phone, no dashboard needed. |
| Git tip at lock | `main` @ `984aceb` — see tag `milestone/eureka-telegram-bot` |

## What was true at this milestone

- **Bot:** `@vigil_akay_bot` on Telegram, live on the ThinkPad.
- **Stack (named layers):**
  - **COURIER** — Hermes Telegram inbox + send (`job_engine/hermes_plugins/vigil-image-only/`).
  - **DIRECTOR** — OpenAI Agents SDK reasoner + skit + tool chooser, `SQLiteSession` memory per `{bot}:{chat_id}` (`job_engine/app/director/`).
  - **STAGEHAND** — Ultron / Watch Tower fact APIs (Postgres truth, never invented numbers).
  - **LENS** — Replicate image generation for visual replies.
  - **CAROUSEL WORKSHOP** — multi-slide album workflow (`/carousel`).
- **Text-first Jarvis chat** (2026-08-04 switch): default chat is text via STAGEHAND + `courier_reply`; `/summarize` drafts from the thread; `/image` generates fact boards / Nano Banana from agreed facts; `/new` clears DIRECTOR memory.
- **Slash boards** (deterministic, no LLM invention): `/towerinsights` `/health` `/hiringsignals` `/searches` `/watchlist` `/fresh` `/brief` `/carousel` `/boards`.
- **Daily brief cron** lands in the same chat every morning.
- Full detail: [`documents/hermes-agent-integration.md`](./hermes-agent-integration.md).

## What shipped right after (not yet in this tag)

Same-day follow-up work, in review, not yet merged to `main`:

| PR | What |
|---|---|
| [#8](https://github.com/akayatgit/global-job-watch-tower/pull/8) | `documents/kanban.md` — engineering execution queue |
| [#9](https://github.com/akayatgit/global-job-watch-tower/pull/9) | Telegram guest access — numeric-id allowlist (`/allow` `/revoke` `/guests`), removes the ThinkPad-terminal dependency for granting access |
| [#10](https://github.com/akayatgit/global-job-watch-tower/pull/10) | Telegram **username** allowlist (`/allowuser` `/revokeuser`) + permanent `DEFAULT_ALLOWED_USERNAMES` (currently `@azr0099`) |

These extend the Eureka bot with multi-user access control; they'll get their own milestone once merged and verified live.

## Why we tagged here

Ashok called this the milestone — the moment the tower stopped being "a dashboard you open" and became "a bot you talk to." Locking a recovery point here so future evolution (multi-user access, richer skits, carousels) stays additive on top of a known-good base, never a rewrite.

## How to recover

```bash
cd /home/user/Documents
git status
git tag -l 'milestone/*'
git checkout milestone/eureka-telegram-bot
# or branch:
git switch -c recover/eureka-telegram-bot milestone/eureka-telegram-bot
```

Do **not** `reset --hard` unless Ashok explicitly orders it.
