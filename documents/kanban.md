# Watch Tower — Engineering Kanban

Execution queue for bugs/ops/infra fixes — distinct from
[`roadmap.md`](./roadmap.md) (the strategic product roadmap tied to the
pitch/PRD). Anything that's "fix this now" lives here; anything that's
"build this feature next" lives in the roadmap.

## How to use this board

1. Pick the **top card in To Do** — that's the next job.
2. Move it to **In Progress** when you start (edit this file, don't just
   remember it — the next session only knows what's written here).
3. When it ships (PR merged + verified, per `deploy-verification.md` if it
   touches the deploy pipeline), move it to **Done** with the PR link.
4. New bugs/fast-follows go to **Backlog** or straight to **To Do** if
   urgent; keep this file as the single source of truth for "what's next."
5. Cards should be self-contained: problem, root cause (if known), approach,
   acceptance criteria, files likely touched — written so a fresh session
   with zero prior chat context can execute without re-investigating.

---

## In Progress

### 1. [URGENT] Telegram guest access — remove the ThinkPad-terminal dependency

**Status (2026-08-04):** Code done, PR up for review. Extended same-day to
add **`@username` allowlisting** (`/allowuser`, `/revokeuser`, and a
permanent code-tracked `DEFAULT_ALLOWED_USERNAMES` set in
`job_engine/app/telegram_guests.py` — currently `@azr0099`) so Ashok can
grant access to a known handle directly, without the numeric-id
`@userinfobot` detour. **One manual ThinkPad step still required before any
of this is live:** set `TELEGRAM_ALLOW_ALL_USERS=true` in `~/.hermes/.env`
and run `hermes gateway restart` (or re-run
`job_engine/scripts/setup_hermes_telegram.sh` / re-bootstrap, which now
defaults to `true`). Until that flip happens, Hermes still silently drops
non-Ashok senders before our new allowlist ever sees them.

**Problem (2026-08-04):** Ashok tried to demo the Telegram bot (`@vigil_akay_bot`)
to an investor. Messages from the investor's phone and his wife's phone got
**zero replies** — only Ashok's own linked account works. He was away from
the ThinkPad with no remote terminal access, so the only known fix (edit
`~/.hermes/.env`, restart the gateway) was impossible to apply live.

**Root cause:** `job_engine/scripts/telegram_watch_tower.py` bootstrap sets
`TELEGRAM_ALLOWED_USERS=<ashok_id>` and `TELEGRAM_ALLOW_ALL_USERS=false` in
`~/.hermes/.env` (outside git). That gate is enforced **inside the external
Hermes gateway binary** (`~/.local/bin/hermes`, not in this repo) — it drops
non-allowed senders *before* our plugin hook
(`job_engine/hermes_plugins/vigil-image-only/__init__.py:112` →
`telegram_to_director`) ever sees the message. So a repo-side fix can't
intercept anything Hermes already silently dropped, and any fix requires
either a terminal on the ThinkPad or a Hermes gateway restart — both were
unavailable at the moment they were needed.

**Approach:** stop relying on Hermes's own allowlist for anything but "is
this bot open at all." Set `TELEGRAM_ALLOW_ALL_USERS=true` permanently in
`~/.hermes/.env` (one-time manual step, needs to happen on the ThinkPad —
note this for whoever picks up the card) so every message reaches our
plugin hook, then build **our own** access control fully inside this repo,
manageable entirely from Ashok's phone via Telegram commands (no SSH, no
laptop, no Cloudflare dashboard):

- New small store (e.g. `job_engine/app/telegram_guests.py` +
  `job_engine/.data/telegram_guests.json` or a DB table) holding
  `{telegram_user_id, added_by, expires_at, label}`.
- In `telegram_to_director` (or a new pre-check called from it), before
  dispatching to DIRECTOR: allow if `from.id` is the primary owner
  (Ashok's id, from `~/.hermes/watch_tower_telegram.json`) **or** a
  non-expired guest row. Otherwise reply nothing (keep current silent
  behavior for randoms) or a short "ask the owner to `/allow` you" — Ashok's
  call, default to silent to match existing private-ops posture.
- Admin-only commands, usable only by the primary owner:
  - `/allow <user_id> [minutes=60]` — add/refresh a guest, default 60 min.
  - `/revoke <user_id>` — remove immediately.
  - `/guests` — list active guests + remaining time.
- Getting a guest's numeric Telegram id: have them message
  [@userinfobot](https://t.me/userinfobot) once (safe, doesn't touch our
  bot's state) and read their `Id` back to Ashok.

**Acceptance criteria:**
- From his own phone only (no ThinkPad access), Ashok sends
  `/allow <investor_id> 60` → investor's next message gets a real DIRECTOR
  reply → after 60 minutes it silently stops working again → `/guests`
  shows the active entry and countdown → `/revoke` removes access
  immediately.
- Works whether or not Ashok has any ThinkPad/terminal/Cloudflare access at
  the time.
- Document the one-time `TELEGRAM_ALLOW_ALL_USERS=true` manual step (and
  why it's now safe — our own gate replaces it) in
  `documents/hermes-agent-integration.md`.
- **Username variant:** a handle in `DEFAULT_ALLOWED_USERNAMES` (or granted
  via `/allowuser <handle>`) gets a real DIRECTOR reply with **no** numeric
  id ever exchanged; `/guests` lists allowed usernames alongside numeric
  guests; `/revokeuser` removes a granted handle (defaults require a code
  change, by design).

**Files:** `job_engine/hermes_plugins/vigil-image-only/__init__.py`,
`job_engine/app/director/router.py`, `job_engine/app/telegram_guests.py`,
`job_engine/app/api/routes.py`, `job_engine/scripts/telegram_watch_tower.py`
(bootstrap defaults), `documents/hermes-agent-integration.md`.

---

## To Do

### 2. Verify + lock Cloudflare Access properly

**Deprioritized (Ashok 2026-08-04):** "Not a high priority, I didn't share
the URL with anyone and never will." Stays on the board (unshared URL is
obscurity, not a lock — revisit before any public/investor share or before
Gate 2 content goes out), but nothing blocks on it.

**Problem:** `documents/remote-access-cloudflare.md` still flags Access as
**not verified** — as of 2026-08-03, an unauthenticated GET to
`https://tower.jobmaster.agency` served the live VIGIL dashboard directly,
no login gate. On 2026-08-04 this was used as a fallback "maybe it just
works" demo path — that's a live data-exposure risk sitting unresolved,
not a feature to rely on again.

**Approach:** follow the "Access fix" checklist already written in
`remote-access-cloudflare.md` (§ Access fix) on the Cloudflare Zero Trust
dashboard. Confirm in an Incognito window that the OTP/email gate appears
*before* VIGIL loads.

**Acceptance criteria:** Incognito test shows the Cloudflare Access login
screen first, VIGIL only after passing it. Update
`remote-access-cloudflare.md`'s "Live stamp" row from "must be verified" to
**LOCKED** with the verification timestamp.

**Files:** `documents/remote-access-cloudflare.md` (doc only — the actual
fix happens in the Cloudflare Zero Trust dashboard, not in this repo).

---

## Backlog

### 4. Gate 1.1 — tower as a plug-and-play Docker image (Ashok 2026-08-04)

**Status (2026-08-04): code done + verified on a blank cloud VM.** Full stack
(`db → migrate → api/worker/beat`) booted from scratch, VIGIL served at
`:8002`, migrations clean, worker ready, orb version visible in-container.
See `documents/docker-plug-and-play.md`. Remaining nice-to-have: milestone
image tagging convention in CI (documented, not automated).

**Ask:** "setup as a docker image to just plug and play anywhere."

**What shipped:**
- Multi-stage `job_engine/Dockerfile` (VIGIL vite build + Python app +
  repo `VERSION`), root `.dockerignore`, build context = repo root.
- Compose grew `migrate` (one-shot alembic), `worker`, `beat`, healthchecks,
  enforced boot order.
- scrapling fresh-install import crash patched at build (UA pin 149 → 141;
  upstream data only ships ≤141 — see doc).
- `documents/docker-plug-and-play.md` — one-command run, smoke checks,
  what's deliberately host-only (Chrome profile, Ollama, `~/.hermes`).

### 3. General remote break-glass access to the ThinkPad

Today's incident (no SSH, no Tailscale, only an HTTP tunnel — see
`documents/remote-access-cloudflare.md` "What we deliberately do not do")
means any ThinkPad-side config change requires physical presence. Card #1
solves this for the Telegram case specifically by moving control into
Telegram itself. Consider whether other "Ashok is away, needs to change
something now" cases need the same pattern (e.g. a tiny authenticated admin
action inside VIGIL itself, reachable once Cloudflare Access is locked per
card #2).

---

## Done

| Card | PR | Date |
|---|---|---|
| Deploy verification check + fix `documents/briefs` dirty-file wedge (attempt 1 — insufficient alone) | [#5](https://github.com/akayatgit/global-job-watch-tower/pull/5) | 2026-08-04 |
| Build version counter + orb dot-color signal + rail version footer | [#6](https://github.com/akayatgit/global-job-watch-tower/pull/6) | 2026-08-04 |
| Actually unblock the deploy pipeline (fix lives in workflow YAML, not the gated script) | [#7](https://github.com/akayatgit/global-job-watch-tower/pull/7) | 2026-08-04 |
