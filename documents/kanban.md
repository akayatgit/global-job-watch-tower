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

### 5. Public carousel — clean modern design with real tower data (Ashok 2026-08-04)

**Status (2026-08-04):** Slice 1 shipped — rotating art-direction engine.
Ashok: *"the current carousel is shitty, it is sticking to one prompt, and
creates the same"* — prioritized ABOVE the Trendjack gig ("no time for
gimmicks"). Root cause found: `graphic_carousel_prompt` was ONE hardcoded
template reused for every slide of every run, leaving "invent a unique data
metaphor" to the image model — which converged to the same picture forever.

**Fix shipped (slice 1):** `job_engine/app/prompt_dictionary.py` now has
`CAROUSEL_THEMES` — 6 complete art directions (midnight editorial · swiss
paper minimal · terminal pulse · dusk gradient signal · brutalist poster ·
ink and gold) — plus per-slide-role layout specs (hook / big-number /
ranked-list / rising / stat-chips / cta). One theme per RUN (coherent album),
counter file `.data/carousel_theme_seed.txt` guarantees the NEXT run uses a
DIFFERENT theme. All numbers stay verbatim tower facts; prompt guardrails
(min length, leak markers) still enforced. 36 theme×slide combos verified.

**Bug found live (2026-08-04, Ashok's first test):** sending "Carousel" on
Telegram returned *"No fresh job openings found with the keyword
'Carousel'"* — the DIRECTOR LLM treated the word as a job-search keyword.
Root cause: the "Carousel word = separate album workflow" route lived in the
OLD entry script (`scripts/telegram_watch_tower.py` `cmd_image_chat`), but the
plugin now dispatches everything to `app/director/router.py`, which had no
carousel route. Fixed: deterministic `\bcarousel\b` route in the router
(before the LLM ever sees it) → ack text → `cmd_send_carousel(topic_msg)` →
album to Telegram, with trace + failure message. Same loophole class as the
old `title="fresh"` bug.

**Next slices:**
- Ashok is sending Pinterest inspiration URLs → tune/replace themes to match
  his taste (themes are data, easy to swap).
- Render a real album per theme on the ThinkPad (needs Replicate token) and
  let Ashok pick keepers / kill weak themes.
- Consider Pillow-composited exact-text layer if Nano Banana misspells
  numbers on ranked-list slides (data authenticity rule).

### 6. [URGENT] Restore Ashok-only Telegram command deck

**Status (2026-08-04, 23:23 UTC):** Ashok's `/stats ai`,
`/hiringinsights`, and `/governmentjobs` were falling into ordinary JobMaster
search parsing after the dedicated-ingress cutover. Root cause: Gate 3.0
replaced Hermes `quick_commands`, but the new poller restored only `/new` and
generic help—not the deterministic VIGIL command router or Telegram command
scope.

**Deployed (2026-08-05, 04:50 UTC):** the dedicated JobMaster service routes
live VIGIL boards and grounded shortcut queries before normal search parsing.
Commands are authorized only when `chat_id == TELEGRAM_HOME_CHANNEL`. Startup
clears default and all-private Telegram menus, then installs the command deck
with a chat-specific scope for Ashok. Other users retain the same clean
JobMaster conversation and cannot invoke VIGIL operations. Production SHA
`af5c1ea`; contract suite 38/38 green; deployment diagnostics PASS; exactly one
JobMaster poller; Hermes off; interrupted `AI/ML Intern` search retriggered.

**JM-002 live failure (2026-08-05, 05:43 UTC):** Ashok opened the menu and
found user management missing. Gate 3.0 had restored insight commands but not
the former phone-only allow/revoke controls, and the dedicated poller was not
enforcing the managed guest store. Recovery in review adds Ashok-only
`/allowguest`, `/blockguest`, and `/guests`; explicit blocks override default
usernames, re-allow clears a block, numeric access can expire, owner access
cannot be blocked, and unauthorized updates are rejected before entering the
durable processing queue. Access mutations are serialized across processes;
owner changes form an update-order barrier; queued/prepared replies recheck
access; corrupt state fails closed. Contract suite: 50/50 green; focused
security audit: no remaining high/medium findings.

**Acceptance:** follow
[`jobmaster-telegram-validation.md`](./jobmaster-telegram-validation.md);
confirm Ashok sees and can run all owner menu commands; allow, list, block, and
re-allow a test account; then confirm a blocked account receives no reply and
Supriya does not see the command deck or expose tower operations. Keep this
card open until Ashok accepts the live result.

### 8. Ashok-only guest conversation history

**Request (2026-08-05, 10:05 UTC):** after allowing `@cryptoonz`, Ashok needs
to inspect guest test conversations from Telegram itself, with an owner command
returning at most the latest 40 conversation pairs.

**Important limit:** Telegram Bot API cannot retrieve messages retroactively.
History begins after this feature deploys; earlier `@cryptoonz` replies are not
recoverable from Telegram.

**Implementation in review:** `/history <@username-or-id> [1–40]` is owner-only.
Delivered guest question/final-reply pairs are archived locally and atomically
removed from the durable inbox. Retention is strictly 40 per numeric chat,
including migration cleanup. Owner traffic is excluded. Username grants bind
to the first stable numeric ID; recycled/ambiguous usernames fail closed;
observed aliases remain blockable. Output is a single compact response capped
at 3,700 UTF-16 units. History failure cannot strand the chat queue.

**Evidence:** 66 combined Telegram/search tests green; focused security review
reports no remaining high/medium privacy, authorization, retention, durability,
or delivery findings.

**Acceptance:** after deploy, `@cryptoonz` sends one normal query; Ashok runs
`/history @cryptoonz 40` and sees only that guest's delivered conversation;
Supriya's same history command exposes nothing. Keep open until Ashok accepts.

## Done

### 1. [URGENT] Telegram guest access — remove the ThinkPad-terminal dependency

**LOCKED — Ashok accepted the live result (2026-08-04, 23:14 UTC):**
*"It's definitely better, lock this and let's develop from here."* JobMaster
capability #1 is the new baseline at `main` commit `2fda2d7`, tagged
`milestone/jobmaster-gate3-v1`. The incident closes only because Ashok verified
the real Telegram experience after deployment—not because code merged or tests
passed.

**Gate 3.0 recovery (2026-08-04, 21:10 UTC):** RCA proved Supriya's malformed
AI/fresher reply and `/new` model banner came from Hermes' built-in Qwen agent;
the deployed interception hook was no longer in the message path. Recovery PR
replaces Hermes Telegram ingress with one dedicated JobMaster service. Every
user gets the same focused capability #1: natural-language intent understanding,
verified LinkedIn jobs, grounded market numbers/comparisons, `Thinking…`, 10
rows, `more`, and a clean `/new`. Mock contract suite is green and Ashok accepted
the production result after Supriya's live test.

**Status (2026-08-04, evening):** Manual ThinkPad step ELIMINATED — deploy
now owns the Hermes gateway. Live failure that proved it: Ashok's wife
(`@Supriyamk`) sent "hi" and got silence even after `/allow`, because (a) the
gateway still had `TELEGRAM_ALLOW_ALL_USERS=false` and dropped her before the
plugin, (b) the gateway never restarts on deploy so plugin code was stale,
and (c) every DIRECTOR reply was hardcoded to `TELEGRAM_HOME_CHANNEL` — even
an allowed guest's answers would have landed in Ashok's chat. All three fixed:
`scripts/deploy_local.sh` now flips the gate flag + restarts the gateway on
every deploy; router sets `DIRECTOR_TARGET_CHAT` (sender's chat) and all four
send paths (courier text, fact boards, lens images, carousel) honor it;
`@supriyamk` added to `DEFAULT_ALLOWED_USERNAMES` (with `@azr0099`).
Telegram bots cannot DM first — guests must send one message, then Vigil
replies in their chat.

**Second root cause found via remote diagnostics (2026-08-04 night):** the
Hermes gateway loads plugins from `~/.hermes/plugins/vigil-image-only/` — a
one-time COPY (9.5 KB) that no deploy ever refreshed, while the repo version
had grown to 13.5 KB. Every plugin change shipped today (username allowlist,
`/allowuser`, sender-username extraction) never actually ran. Log proof:
`DIRECTOR blocked unauthorised chat=1221647274 text=Hi` after the allowlist
deploy, and `guest-reply failed chat=supriyamk: HTTP 400` (old code treating
a handle as a numeric chat id). Fix: deploy now re-copies the plugin dir
into `~/.hermes/plugins/` before every gateway restart, plus a one-time
marker-guarded welcome message to the wrongly blocked chat. Lesson: deploy
script changes take effect only on the NEXT run (bash reads the file that
`git reset --hard` replaces mid-run) — always trigger a follow-up deploy
after editing `scripts/deploy_local.sh`.
Remote debugging now standard: every deploy prints redacted Hermes
diagnostics (`scripts/hermes_diagnostics.sh`) in the Actions log.

**Guest soul shipped (2026-08-04, late night):** wife's "hi" was answered by
the Hermes BUILT-IN agent (skills/platform essay — engine-room talk to a job
seeker). Fixes: (1) plugin returns skip IMMEDIATELY for guest chats (no
600s join) so the built-in agent can never win a race; (2) new **guest
persona** end-to-end (plugin `--persona guest` → router).

**v2, same night — killed the LLM entirely for guests:** even with the
guest persona above, the LLM agent still drifted on a follow-up question
("data science jobs bangalore") — invented salary bands, speculated
employers ("typically at Google/Amazon/Zoho"), a chatty generic-assistant
greeting by her first name, and **zero links**. This is the exact
hallucination class boards were fixed for on 2026-08-02 ("Boards are now
deterministic text — no LLM rewrite"). Applied the same medicine: guests
now get `app/director/guest_reply.py` — a pure-Python parse-role/city →
hit `/api/jobs` + `/api/ultron/tower` directly → format function. Zero LLM
calls in the guest path. Every row requires a real `job_url` or it is
dropped; one factual tower-stat line; friendly deterministic greeting for
"hi"/blank asks. Verified with mocked-network unit tests (extraction,
dedup, no-link exclusion, empty-match fallback). Owner chat (full Jarvis,
LLM) unchanged.

**Third layer, same night — closed the exception escape hatch:** the
diagnostics log from that exact minute showed
`gateway.platforms.base: Sending response (2580 chars) to <guest chat>` —
Hermes' OWN send path, not ours — right where our plugin should have
returned a plain skip. Per Hermes' documented `pre_gateway_dispatch`
contract: "exceptions in plugin callbacks are caught and logged; the
gateway always falls through to normal dispatch on error." Any uncaught
exception anywhere in our hook hands the message straight to Hermes'
ungoverned built-in agent. Fixed: the entire hook body now runs inside an
outer guard (`telegram_to_director` → `_telegram_to_director_inner`) that
can never raise — on any error it logs, sends a short safe apology, and
always returns `{"action": "skip", ...}`. Verified with a simulated crash:
outer function still returns a clean skip dict, never propagates.

Earlier same day: added **`@username` allowlisting** (`/allowuser`,
`/revokeuser`, permanent code-tracked `DEFAULT_ALLOWED_USERNAMES` in
`job_engine/app/telegram_guests.py`) so Ashok can grant access to a known
handle directly, without the numeric-id `@userinfobot` detour.

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

### 7. Automate the JobMaster Telegram acceptance suite

**Source contract:**
[`documents/jobmaster-telegram-validation.md`](./jobmaster-telegram-validation.md).
Ashok will first run its stable `JM-*` cases manually, one by one. Preserve those
IDs when automating so a live failure maps directly to a regression test.

**Slices:**

1. Contract tests for command authorization, intent, output integrity,
   pagination, no-match behavior, and prompt-leak attacks.
2. Telegram sandbox bot for menu scopes, delivery retry, FIFO, and restart
   persistence without spamming production users.
3. Read-only production smoke for owner command, grounded search, canonical
   links, and guest command denial.
4. Deployment gate for exact SHA, one poller, Hermes off, owner menu ready, and
   cancelled-role retrigger evidence.
5. Nightly alias, typo, experience, time-window, deep-pagination, and injection
   corpus.

**Acceptance:** every automatable `JM-*` case reports pass/fail with captured
evidence; destructive/outage cases run only in an isolated sandbox; no paid
image credits or live LinkedIn searches are consumed without approval.

### 2. Verify + lock Cloudflare Access properly

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

## Earlier Done

| Card | PR | Date |
|---|---|---|
| Deploy verification check + fix `documents/briefs` dirty-file wedge (attempt 1 — insufficient alone) | [#5](https://github.com/akayatgit/global-job-watch-tower/pull/5) | 2026-08-04 |
| Build version counter + orb dot-color signal + rail version footer | [#6](https://github.com/akayatgit/global-job-watch-tower/pull/6) | 2026-08-04 |
| Actually unblock the deploy pipeline (fix lives in workflow YAML, not the gated script) | [#7](https://github.com/akayatgit/global-job-watch-tower/pull/7) | 2026-08-04 |
