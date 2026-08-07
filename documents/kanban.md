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

### 15. Job alerts ("Set alert every day") + owner push notifications

**Request (2026-08-07):** Ashok — "job alerts is all the guests who search
for a particular job once they land on job listings... right next to more
options we need to have another button called set alert every day... in
every time when vigil scraps the same job role for the same city... whoever
subscribes to that search has to receive that job alert... standard list of
title with the LinkedIn URLs." Plus owner-side: "`/push` ... can send an
alert or an announcement or a push notification with image or text or with
both image and text together ... everybody who has subscribed to our vigil
bot." Follow-ups: broadcast reaches "every guest who clicked on start", 3
consecutive unanswered pushes temporarily drops a subscriber, add a 👍 Like
button next to every stop button, and a small hint line explaining how to
stop. Not a premium feature — Vigil 2.0 monetization stays out of scope,
this is pure retention/re-engagement.

**Shipped:**
- `app/telegram_sessions.py` — 3 new SQLite tables: `job_alerts` (one row
  per guest+role_family+city+experience subscription, `sent_job_ids_json`
  dedupe list, `likes` counter, max 3 active per guest), `broadcast_subscribers`
  (every chat that ever tapped start, `pushes_since_response` counter),
  `broadcast_pushes` (audit trail: text/photo, recipient + like counts).
- `app/telegram_alerts.py` (new) — subscribe/dedupe/cap logic, reuses
  `JobMasterEngine`'s own `_matches_role`/`_matches_city` + `/api/jobs` HTTP
  client (never a second notion of "is this a match"), matches at
  role_family + city + experience (not the narrow button keyword — same
  class of gap already fixed for live search), formats up to 10 new jobs/
  message with a 👍 Like + 🔕 Stop this alert keyboard and a hint line.
- `app/telegram_broadcast.py` (new) — broadcast-subscriber lifecycle
  (`record_start`/`record_activity`/`stop`) and `send_broadcast` fan-out with
  injectable send function (testable without a real bot token).
- `app/telegram_buttons.py` — "🔔 Set alert" button on every results screen
  next to "🔄 New search"; `ButtonFlow.start()` now also registers the chat
  as a broadcast subscriber (covers `/start`, greeting, and `/new`-triggered
  restart, since all three call `start()`).
- `scripts/telegram_job_bot.py` — new guest command `/myalerts` (list +
  per-row 🔕 stop, same rendering as the underlying data everywhere);
  Ashok-only `/push <text>` (stage) → `/pushconfirm` (send, 10-min TTL) /
  `/pushcancel` / `/pushstats`; photo+caption `/push ...` supported via
  `TelegramAPI.send_photo` and an out-of-band `pending_push_photo:<chat>`
  stash (the durable inbox stays text-only by design); `alert:off:<id>` /
  `alert:like:<id>` / `push:stop` / `push:like:<id>` callbacks handled
  directly (independent of wherever the guest's own button-flow session
  currently is) before falling through to `ButtonFlow`; every accepted
  inbound update from a non-owner chat calls `telegram_broadcast.
  record_activity` (any interaction reactivates a pruned subscriber); a
  background daemon thread dispatches due alerts at most once per UTC day.

**Design decisions (asked/answered inline, not deferred):**
- Broadcast audience = every guest, full stop — not just alert subscribers,
  and (fixed 2026-08-07, see fast-follow below) not only chats that
  literally tapped `/start` either.
- 3 consecutive unanswered pushes → `active=0` (temporarily dropped); ANY
  interaction anywhere in JobMaster (not just replying to a push) sets
  `active=1` again — no manual re-opt-in flow, per "temporarily."
  Explicitly tapping 🔕 Stop notifications does the same `active=0` and is
  reversible the same way, kept as one unified mechanism for simplicity.
- Alert matching is family + city + experience (fresher-only for now,
  matching GTM scope), not the exact role_keywords a button chose.

**Evidence:** new `test_telegram_alerts.py` (12 tests: create/dedupe/cap,
seeding sent-ids from what's already shown, dispatch only sends genuinely
new matches, family-level matching, city exclusivity) + new
`test_telegram_broadcast.py` (11 tests: start/stop/reactivate lifecycle,
3-unanswered-push drop + reset-on-activity, fan-out with like/stop buttons,
partial-failure resilience, push stats) + extended `test_telegram_buttons.py`
(9 new tests: Set alert button present, subscribe/dedupe/cap/seed behavior,
graceful no-prior-search case, broadcast start registration) + extended
`test_telegram_job_bot.py` (23 new tests: `/myalerts`, direct alert/push
callbacks incl. cross-chat ownership refusal, full `/push`→`/pushconfirm`
staging/send/cancel/expiry/stats flow, photo-caption staging, normalize_update
photo support). Full suite: **281/281 green.**

**Acceptance:** Ashok completes a real search on Telegram, taps "🔔 Set
alert", confirms `/myalerts` shows it and 🔕 stops it cleanly; runs `/push`
with text-only and with a photo+caption, confirms the staged preview/
recipient count, `/pushconfirm` delivers to a real second account with 👍/🔕
buttons and the hint line, `/pushstats` reflects reach+likes; confirms a
guest who never replies to 3 pushes stops receiving a 4th, then any message
from them brings them back. Keep open until Ashok accepts the live result.

**Fast-follow fix (2026-08-07, same day):** Ashok ran `/pushconfirm` for real
and azr0099, supriyamk, cryptoonz — guests he has conversation history with —
never got it. Root cause: `broadcast_subscribers` only ever got a row via
`ButtonFlow.start()`, which only fires on a literal `/start`, a bare
greeting, or `/new` — a guest whose very first message is already a full
query (e.g. "AI jobs in Bangalore") never calls it, and the table itself
didn't exist before this card shipped so nobody's pre-existing history was
in it either. Ashok's correction: "everyone who are guests is the only
condition" — no narrower gate than that. Fix:
- `TelegramSessionStore._backfill_broadcast_subscribers` runs on every store
  startup (same idempotent-maintenance pattern as the 40-row conversation
  prune) and INSERT-OR-IGNOREs every chat_id already seen in
  `conversation_history` / `guest_profiles` / `onboarding_sessions` as an
  active subscriber — never touches a chat_id already tracked (so an
  explicit stop or in-progress unanswered-push count survives), and skips
  chat_ids in `telegram_command_owner_ids` (Ashok's own chat isn't a "guest").
- `record_broadcast_activity` is now an upsert (delegates to
  `record_broadcast_start`) instead of update-only, so a brand-new guest is
  enrolled the moment they send anything — not only when they explicitly
  start — since the bot already calls `record_activity` on every accepted
  guest update.
No new tables/commands; existing `/push` flow, caps, and lifecycle
(3-unanswered-push drop, like/stop buttons, hint line) are unchanged. Full
suite: **285/285 green** (4 new backfill tests in
`test_telegram_broadcast.py`, 1 lifecycle test rewritten to match the
broadened condition).

**Files:** `job_engine/app/telegram_sessions.py`,
`job_engine/app/telegram_alerts.py` (new),
`job_engine/app/telegram_broadcast.py` (new),
`job_engine/app/telegram_buttons.py`, `job_engine/scripts/telegram_job_bot.py`,
`job_engine/tests/test_telegram_alerts.py` (new),
`job_engine/tests/test_telegram_broadcast.py` (new),
`job_engine/tests/test_telegram_buttons.py`,
`job_engine/tests/test_telegram_job_bot.py`, `documents/roadmap.md`,
`.cursor/rules/product-ux.mdc`, `documents/jobmaster-telegram-validation.md`.

### 13. Open the Gate — public access, no more allow-one-by-one

**Request (2026-08-06, 14:14 UTC):** Ashok, right after accepting card #11 at
99/100 — "1 lakh people will not flood overnight 😂 ... we are just going to
let 'Vigil' the guest chatbot come online, so we can start spreading about it
... ship it to anyone who has the link ... **Open the Gate** ... Allow all
the guests, no need for me to give allow one by one ... let anyone be the
guest the moment they say hi or hey or hello anything they talk to."

**Shipped:** `app/telegram_guests.py::is_allowed()` flipped from
allow-list-by-default to **open-by-default**: the owner is always allowed;
`/blockguest` (numeric id) / `/blockuser` (@handle) is now the *only* thing
that denies access; every other sender — granted or not — is allowed the
instant they message. `DEFAULT_ALLOWED_USERNAMES`, `/allowuser`/`/allowguest`
grants, and the username↔id binding bookkeeping still exist (mostly to
un-block someone or leave a VIP note) but no longer gate anything.
`describe_access()`/`/checkaccess` updated to report `ALLOWED` with an
informational reason instead of denying on a stale/mismatched binding.
`/guests` dashboard rewritten to lead with **Blocked** (the real gate now)
instead of a named allow-list that no longer decides who gets in. No change
needed to the immediate-acknowledgement or button-flow-on-greeting paths —
they already fire for any allowed sender, so opening the gate is what makes
them fire for a genuinely new stranger too.

**Why this matters (Ashok's framing):** JobMaster is going from an invite-only
pilot to "anyone with the link" so word-of-mouth becomes the growth channel.
Immediate acknowledgement (`Thinking…` / instant button prompts) is the
retention mechanism this whole approach depends on — a stranger who says "hi"
must never be silently ignored again (that was the entire class of bug behind
@supriyamk's outage under the old allow-list gate).

**Vision noted, not built (2026-08-06):** Ashok also described **Vigil 2.0**
— the same bot selling affiliate items/ads through earned trust (job alerts,
interview insights, quizzes, links, certification/skill recommendations, then
tasteful high-ticket affiliate offers). Explicitly deferred — "just don't work
on 2.0, but keep it in vision" — recorded as a standing law in
`.cursor/rules/akay-soul.mdc` ("Why this must sell — survival law") and
`.cursor/rules/product-ux.mdc` so future JobMaster decisions keep it viable.
No monetization code in this slice.

**Evidence:** full suite green (230/230) — `test_telegram_job_bot.py` updated:
old deny-by-default binding-conflict tests rewritten to assert the new
open-by-default behavior (`test_username_binding_no_longer_restricts_other_ids_under_open_gate`,
`test_a_stranger_with_no_identity_record_at_all_is_still_allowed`,
`test_checkaccess_allows_a_never_before_seen_stranger`,
`test_checkaccess_notes_a_username_bound_to_a_different_telegram_id_but_still_allows`,
`test_reallowing_a_username_does_not_lift_an_ids_own_block`); block-cascade
tests (blocking a username/id, renamed/recycled aliases) verified unchanged.

**Files:** `job_engine/app/telegram_guests.py`,
`job_engine/scripts/telegram_job_bot.py`,
`job_engine/tests/test_telegram_job_bot.py`, `.cursor/rules/akay-soul.mdc`,
`.cursor/rules/product-ux.mdc`.

**Acceptance:** Ashok merges/deploys, then a brand-new Telegram account with
**no prior `/allowguest`/`/allowuser` grant** messages "hi" and gets an
instant button-flow greeting; `/checkaccess <that id>` shows `ALLOWED`;
`/blockguest <that id>` immediately silences them; `/allowguest <that id>`
brings them back. Keep open until Ashok confirms this live with a real
never-before-seen account (not `/actasguest`).

### 11. JobMaster voice layer (1A) — natural tone around deterministic facts

**Request (2026-08-05):** Ashok — "the chat has no life, we cant run on
Regex, we are in AI era, people want to naturally talk... We need an AI
layer who controls this regex, know our regex rules and convert the request
from guest into regex and get the real info, but support the conversation
with data using regex and basic conversations." Offered two options (1A: LLM
reworded fact-locked replies vs 1B: LLM-free, freeform-slot-filling only);
Ashok picked **1A**. Separately clarified "subscriber" means a future paid
tier (quiz, alerts, flashcards, study materials, prep book, projects,
certifications, LMS) unlocked after sustained usage — explicitly **deferred,
not built this slice** — but the voice layer should stay generic enough
that phase doesn't have to fight hard-coded regex-only assumptions.

**Implementation (in review):** new `job_engine/app/telegram_voice.py`:
- `VoiceLayer.speak(reply)` — best-effort pass through `OPENAI_BRAIN_MODEL`
  (same model as the existing `IntentInterpreter`) with a system prompt that
  allows only added tone/greeting/connective text; every fact line must be
  copied verbatim. Disabled automatically without `OPENAI_API_KEY`, or via
  `JOBMASTER_VOICE_LLM=false`. Any exception/timeout returns the original
  reply untouched.
- `validate_voice(original, candidate)` — byte-exact fact-lock: every
  non-blank line of the deterministic reply must reappear verbatim, in
  order, inside the candidate, and the candidate may not introduce a URL
  absent from the original. Same authenticity-gate pattern as the owner
  Jarvis `app/director/tools_validator.py`, applied to the guest/customer
  surface for the first time.
- Wired into `scripts/telegram_job_bot.py` around the main
  `engine.handle()` reply (job search / insight / onboarding / `/new`) and
  the `/start`/`/help` message only — **not** VIGIL owner board or
  management commands, which stay exactly deterministic. `JobMasterEngine`
  itself, and its full existing contract-test suite, are untouched.

**Follow-up (2026-08-05, same day):** Ashok — "Not sure if the api key of
openai is set in my laptop, add also that /health line." Added a new fact
line to the existing `/health` board (`app/vigil_boards.py`, shared by the
Telegram bot, `/boards` CLI, Hermes/Ask, MCP, and the Ultron web routes):
`JobMaster voice AI: ON (OPENAI_API_KEY set)` /
`OFF (no OPENAI_API_KEY)` / `OFF (disabled via JOBMASTER_VOICE_LLM)` — a
pure local env check (no network, no model call), so Ashok can confirm the
voice layer's actual runtime status from his phone instead of opening a
terminal on the ThinkPad. This line is deterministic text, not LLM-voiced —
`/health` itself is still never passed through `VoiceLayer` (owner boards
stay exact), it just now reports one more true fact.

**Evidence:** `job_engine/tests/test_telegram_voice.py` (validator +
VoiceLayer unit tests, no network/real credentials) +
`test_telegram_job_bot.py::VoiceLayerWiringTests` (voiced vs never-voiced
paths, engine-failure fallback never voiced, durable retry reuses the
already-voiced reply without a second model call) +
`test_vigil_boards_health.py` (new `/health` voice-status line: on/off/
flag-disabled, and that it survives inside the full health board render).
Full suite: **190/190 green.**

**Acceptance:** Ashok runs a live search on Telegram and confirms replies
read like natural conversation (not a rigid template) while every job
title/company/experience/link/count still matches the live tower exactly;
confirms a VIGIL owner command (e.g. `/health`) is unchanged in tone and
now also confirms the new voice-AI status line on `/health` correctly
reflects whether `OPENAI_API_KEY` is set on his laptop. Keep open until
Ashok accepts the live result.

**Files:** `job_engine/app/telegram_voice.py`,
`job_engine/app/vigil_boards.py`,
`job_engine/scripts/telegram_job_bot.py`,
`job_engine/tests/test_telegram_voice.py`,
`job_engine/tests/test_telegram_job_bot.py`,
`job_engine/tests/test_vigil_boards_health.py`, `job_engine/.env.example`.

### 12. Button-driven guest flow (GTM: Intern/Fresher only) + live access diagnostics

**Trigger (2026-08-06):** the voice layer above (card 11) degraded live —
duplicated role labels ("Product Product Manager"), a stray "YES" leaking
in as a role keyword, and the "today" job-count gate silently dropping a
city the guest had already given. Worse: one real guest, Supriya
(`@supriyamk`), stopped getting any reply at all, while Ashok's own
`/actasguest` self-test looked completely healthy.

**RCA — three deterministic bugs (patched, `fdb1c37`):**
1. `_role_label` concatenated `role_family` + `role_keywords` without
   dedupe — fixed by stripping family words from keywords first.
2. `FILLER` didn't include affirmative/negative words ("yes", "no",
   "skip"...), so a bare "yes" reply parsed as a role keyword — added to
   `FILLER` in `app/telegram_job_search.py`.
3. `_role_count` hardcoded `days: 1` and ignored `city` entirely — now
   accepts and threads `city` through to both the Watch Tower query and the
   "no openings today" message.

**RCA — why `/actasguest` missed the real outage:** `_sender_allowed` is
`self._is_owner(chat_id) or is_allowed(chat_id, username)` — for
`/actasguest`, `chat_id` is Ashok's own real owner id, so `_is_owner` is
always `True` and `is_allowed()` (the actual guest gate) never even runs.
The self-test can only ever validate command/reply *content*, never the
access gate itself. Root cause of Supriya's specific outage is still
unconfirmed (requires her live `/checkaccess` or `/guests` result — no
ThinkPad terminal access from this session) — see Acceptance below.

**Ashok's pivot instruction:** "rip that layer out for now, but instead of
free text lets keep the user on a buttons option to filter down the search
one by one... Family, role, experience (Intern, fresher, 1-4, 5-10, 10+)...
for other than intern and fresher, a static message... provide your
emailid... We are going to GTM with only freshers and interns... Dont
disable [voice/AI], keep it as backup plan incase if they text... only if
the button system completely gives up."

**Shipped this slice:**
- `app/telegram_buttons.py::ButtonFlow` — deterministic wizard: **Family →
  Role → Experience → City → Results**, all via Telegram inline keyboards
  (`callback_query`), zero typing required on the primary path. Returning
  guests with a stored Intern/Fresher profile get a one-tap "Welcome back,
  same search?" shortcut.
- GTM gate: only Intern/Fresher experience buttons run a live search (both
  query the shared "fresher" Watch Tower track). Every other band (1–4,
  5–10, 10+) shows a static "coming soon" message and captures an email —
  `app/telegram_waitlist.py` (new JSON store) + owner `/waitlist` command.
- `TelegramAPI.send_keyboard` / `TelegramAPI.answer_callback` — inline
  keyboard delivery and tap-spinner acknowledgement.
- Poll loop now normalizes `message` and `callback_query` updates through
  one shared shape (`JobMasterTelegramBot._normalize_update`) so button
  taps flow through the exact same durable per-chat queue, access gate, and
  rate limiting as typed text (a `\x00` sentinel — `BTN_PREFIX` — tags
  button-tap text; a real Telegram message can never contain a NUL byte).
- Free text is **not disabled** — `/start`, `/new`, and a bare greeting
  launch the button flow, but any other typed message still falls through
  unchanged to the existing `JobMasterEngine` + voice layer, exactly as
  today. A stale `btn_*` onboarding stage is treated as "unknown" by the
  legacy text engine, so it self-heals by restarting instead of getting
  stuck.
- `app/telegram_guests.py::describe_access` + owner-only `/checkaccess
  <@username-or-id> [id-to-compare]` — runs the exact same allow/block/
  binding decision `is_allowed()` makes for a real message, with a
  plain-English reason (blocked, expired, unbound username, username bound
  to a different numeric id, no username on the message at all, etc.) —
  the tool `/actasguest` structurally cannot be, per the RCA above.

**Evidence:** full suite green (230 tests) including new
`test_telegram_buttons.py` (24 tests: family/role/experience navigation,
focus-experience → city → live results incl. pagination and zero-result,
non-focus → waitlist incl. invalid email/skip, restart/welcome-back) and
new `NormalizeUpdateTests` in `test_telegram_job_bot.py` covering the
message-vs-callback_query poll-loop wiring in isolation (this exact
`_normalize_update` method was called before it was defined during
development — caught by this test, not by a human).

**Accepted (2026-08-06, 13:53 UTC):** Ashok — "Im giving you 99/100. We have
an usable product" — after live-testing the full tap-through flow, hitting
the NLP Engineer zero-result case, and confirming the fallback fix. Card
stays open only to capture the missing 1% (see next forward-working
question) and the `@supriyamk` `/checkaccess` root cause below.

**@supriyamk update (2026-08-06, superseded by card #13):** whatever the
exact original cause was (block, stale binding, or a missing username on the
update), it no longer matters — card #13's Open Gate change makes `is_allowed`
allow-by-default, so @supriyamk (and any other never-granted sender) is
allowed regardless of allow-list/binding state from here on. The only way she
could still be silenced is an explicit `/blockguest`/`/blockuser` (check with
`/checkaccess @supriyamk`) or a Hermes-side transport gate outside this repo
(`TELEGRAM_ALLOW_ALL_USERS` on the ThinkPad) — both are one command/one env
var away from confirming.

**Acceptance:** Ashok runs `/checkaccess @supriyamk` live and reports the
verdict/reason; if it comes back "not on the allowlist" or a binding
mismatch, resolve with `/allowuser` (or `/revokeuser` then `/allowuser`) and
have her retry; then confirms the full tap-through Family → Role →
Experience → City → Results flow live end to end for both Intern and
Fresher, confirms a 1–4/5–10/10+ tap shows the coming-soon message and
accepts an email (checked via `/waitlist`), and confirms typing a normal
sentence instead of tapping still gets a real answer (backup path). Keep
open until Ashok accepts the live result.

**Files:** `job_engine/app/telegram_buttons.py`,
`job_engine/app/telegram_waitlist.py`, `job_engine/app/telegram_guests.py`,
`job_engine/app/telegram_job_search.py`,
`job_engine/scripts/telegram_job_bot.py`,
`job_engine/tests/test_telegram_buttons.py`,
`job_engine/tests/test_telegram_job_bot.py`,
`job_engine/tests/test_jobmaster_onboarding.py`,
`job_engine/tests/test_jobmaster_acceptance.py`.

**Live bug found right after merge (2026-08-06, Ashok's first live test):**
tapped AI/ML → NLP Engineer → Fresher → a city and got a dead "No verified
jobs match that search right now" screen. Root cause: `_matches_role`
requires the specific role keyword (`nlp`) to literally appear in the job
title — a real, narrow keyword like that can have zero live postings at any
given moment even though the AI/ML family overall has plenty. This is a
*button-UX-created* problem: free text rarely typed something this narrow,
but a dedicated "NLP Engineer" button makes hitting an empty niche trivial.
**Fixed:** `ButtonFlow._run_search` now retries with `role_keywords=[]`
(exactly what "Any AI/ML role" already searches — same family, never a
different one, so JM056's "no substitution across categories" contract is
untouched) whenever the specific-role search comes back empty, and prefaces
the wider results with "No {role} openings right now — here are other
{family} roles instead." The guest's *actual* pick (NLP Engineer) is still
what gets remembered for "welcome back," not the broadened search shown to
them. New regression test:
`test_a_narrow_role_with_zero_openings_falls_back_to_the_wider_family`.
231/231 green.

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

### 9. Guided guest onboarding + guest profile management

**Request (2026-08-05, 12:03 UTC):** Ashok — "when any guest greets or
starting a conversation, we need to start collecting information gradually,
such as Job Role, [then] I can get you x job roles postings with url, but can
you provide me your experience so I can provide you better matching openings
— fresher. Then do you have a city preference and show for today, forward
ending questions and suggestions. We also need to start user/guest
management."

**Implementation in review:** a bare greeting (`Hi`, `Hello`, `Hey`, `Good
morning`, etc. — fully anchored, never a substring of a real query) now starts
a deterministic 3-step flow instead of returning an unfiltered job dump:
1. **Role** — "What job role are you looking for?"
2. **Experience** — states a grounded live count of matching jobs *today*
   (`/api/jobs/insights?days=1`, never invented) with links, then asks for
   experience (fresher / 1-2 / 3-5 / 6-8 / 9-12 / 13+ / "any").
3. **City** — asks for a city preference ("any" skips the filter), then
   returns up to 10 grounded rows via the exact same `_job_reply` pipeline
   every other search uses, ending with a forward-looking suggestion
   ("Tell me a new role or city anytime...").

Any fully specified message (e.g. `AI jobs in Bangalore for fresher`) is
never redirected into this flow — onboarding triggers only on a literal
greeting, per Gate 3.0's "grounded results immediately" guarantee (verified
by regression test). An eager multi-field answer at any step (e.g. `AI
Engineer, fresher, in Chennai`) skips already-answered questions instead of
forcing the full funnel. Zero-match roles and unrecognized experience/city
answers get an honest, graceful fallback — never a dead end or invented data.
`/new` cancels onboarding cleanly; `more` after completion paginates the
onboarding-originated search exactly like any other. Applies identically to
Ashok and guests (no personality split), per the standing JobMaster rule.

**Guest management:** every completed search that states a role — not only
guided onboarding, but any normal one-shot query like `AI jobs in Bangalore
for fresher` — saves/refreshes a per-guest profile (role, experience, city,
last updated). A later search overwrites the earlier profile; a bare,
roleless query (`jobs`) or an insight-only question never touches it. New
Ashok-only command `/guestprofile <@username-or-id>` reads it back — same
fail-closed ambiguous-username rule as `/history`. `/guests` (access
allow/block list) already existed from card #6; this adds the "what are they
actually looking for" layer on top.

**Addendum (2026-08-05, afternoon) — zero-friction welcome back:** a greeting
from a chat that already has a stored `guest_profile` no longer re-runs the
full role→experience→city funnel. It recalls the stored role/experience/city
deterministically — a template over the same structured fields
`_maybe_save_guest_profile` already writes, never an LLM summary — and offers
"reply `yes` for today's openings, or tell me a new role." `yes` jumps
straight to grounded results with zero extra questions; naming a different
role re-confirms experience/city for that new role only; declining (`no` /
"something else") starts a fresh full funnel. First-time guests with no
stored profile are unaffected — they still get the original funnel from
JM-130. 6 new tests (`JM-148`..`JM-153` below).

**Addendum (2026-08-05, afternoon) — self-test the guest flow, no second
phone:** Ashok — "Is it possible to create something like can switch the
roles by a command and switch back, so I can test the guest flow as well. I
dont have another mobile phone." New Ashok-only `/actasguest` /
`/actasowner` toggle a per-chat "testing mode" flag
(`simulate_guest:<chat_id>` in the existing durable `bot_state` table, so it
survives a service restart):
- `/actasguest` — this chat now gets exactly the guest experience: the
  Telegram command menu is hidden (`deleteMyCommands` on that chat's scope),
  every VIGIL/management command returns the same denial a real guest sees,
  and search/onboarding conversations here are recorded like a guest's
  (`conversation_history`, `guest_profiles`) so `/history` and
  `/guestprofile` can also be exercised end-to-end against Ashok's own chat.
- `/actasowner` — restores the command menu and full owner access instantly.
- **Cannot lock Ashok out of his own chat:** message-queue acceptance
  (`_sender_allowed`) and the toggle commands themselves are always gated on
  the *real* owner check (`_is_owner`, static config), never the simulated
  one — only command *authorization* and history *recording* flip
  (`_effective_is_owner`). A genuine guest typing `/actasguest` gets the
  ordinary owner-command denial and cannot flip anyone's mode. 8 new tests
  (`JM-154`..`JM-161` below).

**Evidence:** `job_engine/tests/test_jobmaster_onboarding.py` (30 tests —
greeting detection, the full flow, zero-match/unrecognized-answer fallbacks,
eager answers, `/new` cancellation, `more` continuity, `/guestprofile`
access control, profile updates from any role-scoped search, and the
welcome-back recall/accept/decline/new-role paths) +
`job_engine/tests/test_telegram_job_bot.py::RoleSwitchSelfTestTests` (8 tests
— command denial while simulating, menu hide/restore, restored access on
`/actasowner`, never-silently-dropped, guest-style history recording, a real
guest cannot flip anyone's mode, idempotent repeat toggles, state survives a
restart). Full suite: **163/163 green.** `JM-130` through `JM-161` in
[`jobmaster-telegram-validation.md`](./jobmaster-telegram-validation.md) §14
for Ashok's live run.

**Acceptance:** Ashok runs JM-130..161 live in Telegram (starting from a
fresh `/new`'d chat) and confirms: the funnel feels natural and the "today"
count is real; a returning guest gets the zero-friction recall instead of
re-answering everything; `/guestprofile` shows what a test guest searched
for; and — using only his own phone — `/actasguest` makes his own chat behave
like a stranger's (menu gone, commands denied, same search experience) while
`/actasowner` instantly gives full access back. Keep open until Ashok accepts
the live result.

**Files:** `job_engine/app/telegram_job_search.py` (onboarding state machine,
welcome-back recall, `_extract_experience`/`_extract_role_family` refactor,
`_role_label`), `job_engine/app/telegram_sessions.py` (`onboarding_sessions`
+ `guest_profiles` tables), `job_engine/scripts/telegram_job_bot.py`
(`/guestprofile`, `/actasguest`, `/actasowner`, `_effective_is_owner`,
`_toggle_role_switch`), `job_engine/tests/test_jobmaster_onboarding.py`,
`job_engine/tests/test_telegram_job_bot.py`,
`documents/jobmaster-telegram-validation.md`.

**Bug found + fixed during Ashok's first live test (2026-08-05, 14:18 UTC):**
Ashok greeted the bot, then answered the role step with the bare word
`Product` (the onboarding prompt's own example says "Product Manager") and
got a false dead end: *"I don't see verified Product openings today. Want to
try a different role?"* — even though real Product Manager postings existed.
**RCA:** `_extract_role_family` only matched the full phrase "product
manager/owner/analyst", never the bare category word, so `Product` fell
through with `role_family=''` and only a loose `product` keyword, which a
stricter title-terms scan can miss. (Confirmed via the deploy's redacted
diagnostics: the `/actasguest`/`/actasowner` toggle, onboarding funnel, and
`/history` text were all exactly the newly-deployed code — this was a real
parser gap, not a stale process or a rogue LLM reply.) **Fix:** bare
`product` now resolves to the `product` family exactly like `Product
Manager` would; the strict phrase match stays intact as the job-title-side
filter (`job_role_families.ROLE_FAMILY_REGEX`), which is correctly narrow
since real postings are never titled bare "Product". 2 new regression tests
(one on the parser, one on the full onboarding flow) — **165/165 green.**

**Second bug found + fixed in the same live test session (2026-08-05, 14:40
UTC):** Ashok sent `AI ML` as a plain message and got the generic *"JobMaster
provides verified jobs and live job-market insights."* line instead of real
search results. **RCA:** this is the `kind == 'help'` branch in
`JobMasterEngine.handle` — the live OpenAI-backed `IntentInterpreter`
classified `AI ML` as `kind='help'` (ambiguous two-letter-abbreviation
fragment, no verb) even though the deterministic fallback parser plainly
recognizes it as `role_family='ai_ml'`. This never showed up in the mocked
suite because every existing test builds the engine with
`IntentInterpreter(enabled=False)`, bypassing the real model call entirely —
the gap only exists at the live LLM boundary. **Fix:** `IntentInterpreter.
_validate` now refuses to let the model's `kind='help'` override a message
where the deterministic fallback already found a clear `role_family` —
`role_keywords` is deliberately excluded from this guard since it can pick
up ordinary leftover words from genuinely help-ish chatter (e.g. "what can
you do"), so only the clean `role_family` signal overrides "help". 2 new
tests exercising the model-output validation boundary directly. **167/167
green.**

## Done

### 14. Milestone locked — `milestone/jobmaster-agency-1.0`

**Request (2026-08-06, 15:56 UTC):** Ashok — "label it as Jobmaster.agency
1.0, save it as a milestone, point to last revert to in github... this is a
working first mastercopy, we should never mess this up, we can always come
back to this point anytime and we are still in the market."

**Shipped:** annotated git tag `milestone/jobmaster-agency-1.0` at main's tip
`e78f5856ee2b07fc6c46242bd0c669e6c8a2f0a0` (right after card #13's Open the
Gate merged and deployed clean — see `JOBMASTER_TELEGRAM_VERDICT=PASS` in
that deploy run). Same convention as the earlier `milestone/eureka-telegram-
bot` tag. Covers everything shipped through card #13: Gate 3.0 JobMaster,
guided onboarding + button-driven guest flow, GTM Intern/Fresher-only +
experienced-hire waitlist, voice layer (1A) as an unseen free-text fallback,
public Open Gate access, `/checkaccess`, full owner command deck. 230/230
tests green at this commit. Verified pushed and visible under Tags on GitHub.

**Recovery instructions (if `main` ever regresses):**
```
git fetch origin milestone/jobmaster-agency-1.0
git checkout milestone/jobmaster-agency-1.0   # inspect it safely first
# only if Ashok confirms a real revert is needed:
git checkout main && git reset --hard milestone/jobmaster-agency-1.0
```
Never delete this tag. Recorded in `.cursor/rules/akay-soul.mdc`.

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

1. **Contract tests for command authorization, intent, output integrity,
   pagination, no-match behavior, and prompt-leak attacks — done (2026-08-05).**
   `job_engine/tests/test_jobmaster_acceptance.py` adds 58 tests tagged with
   their `JM-*` IDs (040–049, 050–057, 063–067, 070–078, 080–090, 100–108,
   020–037), on top of the 67 pre-existing contract tests in
   `test_telegram_job_bot.py` / `test_telegram_job_search.py`. Full suite:
   **125/125 green.** `.github/workflows/deploy-thinkpad.yml` gained a
   GitHub-hosted `test` job that the self-hosted `deploy` job now `needs:` —
   a code regression fails CI before it ever reaches the ThinkPad, not just
   after via post-deploy diagnostics.

   **Three real bugs caught and fixed while building the suite** (would have
   surfaced as live `JM-*` FAILs otherwise):
   - `_fallback_intent` never assigned `role_family='product'` or `'design'`
     even though `ROLE_FAMILY_REGEX` defines both — `UI UX designer` (JM-048)
     and `product manager` (JM-049) searches were unscoped. Fixed.
   - Job search only ever filtered by `intent.cities[0]`, silently dropping a
     second stated city (JM-084, `"AI jobs in Bangalore and Chennai"`)
     instead of keeping both or explaining the limit. Fixed: job search now
     keeps and matches on all stated cities when the API can't take more than
     one, exactly like the insight/compare path already did.
   - The fresher-experience regex didn't accept the plural `"...for fresh
     graduates"` (JM-041's literal wording) or bare `"graduates"` — only the
     singular. Fixed.
   - Minor: `years`/`yrs` leaked into `role_keywords` when a stated number was
     out of the supported experience-band range (e.g. "200 years"), narrowing
     future searches for no reason. Added to the filler-word list.

   Remaining out of automated scope by design (need a real Telegram client,
   deploy, or live LinkedIn data): JM-001, JM-002 (menu *visibility*, content
   is covered), JM-052 (open every URL), JM-065, JM-078, JM-120–129.

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

*(Cards 15–20 parked here per Ashok 2026-08-06 — "add all these in backlog,
at last we will place in iteration planning". Ordering happens in the next
iteration-planning ritual, not here.)*

### 15. Job Alerts 🔔 — SIPROG epic (specced, awaiting planning)

Full Jira-style breakdown already written: epic + SIMET tasks/bugs with AC,
DoD, t-shirt sizes, and checklists in
[`documents/jira/page-1-siprog-epic.csv`](./jira/page-1-siprog-epic.csv) and
[`documents/jira/page-2-simet-tasks.csv`](./jira/page-2-simet-tasks.csv).
First retention loop: guests opt in after a search, tower pushes fresh
matching jobs daily. Feeds the selling-engine vision (alerts = the ad space).

### 16. Guest analytics — daily funnel numbers for the owner

How many strangers said hi, how many finished the button flow, how many got
jobs vs zero-result dead ends, how many hit the waitlist branch, repeat-guest
rate. Deterministic counts from `telegram_sessions` / delivered history —
never model-estimated. Surfaces in a `/stats` upgrade + VIGIL panel.

### 17. Share hook — happy guests spread the bot

After a successful result set, offer a one-tap "Share JobMaster" button
(Telegram share deep-link with a friendly preheader). Word-of-mouth is the
GTM engine; zero paid acquisition. Measure via guest analytics (#16).

### 18. Guest feedback capture

One-tap 👍/👎 after results + optional short text. Stored deterministically,
readable via an owner command. Feeds iteration planning with real guest
voice instead of guesses.

### 19. `/health` owner board redesign — digestible in 30 seconds

Ashok (2026-08-06): current board is "ugly data … for an owner". Redesign:
verdict first (one line: healthy / degraded + why), human words, and the
numbers an owner actually needs — searches done vs planned today
(e.g. `4/135 roles`), jobs caught today, browser opens (true count incl.
enrichment sessions — see #20 finding), capacity vs plan, next search.
Detail on demand below the fold. Mock approved in the 2026-08-06 planning
chat; build after iteration planning.

### 20. Coverage + capacity monitoring — never discover "only 4 searches" by accident

Findings from the 2026-08-06 investigation:
- `browser_open` events fire only in the scrape session — the enrichment
  backfills (every 10/15 min) open a real StealthySession browser without
  recording it, so browser activity is undercounted.
- 135 enabled roles vs a measured ~15 min/search on one worker = a hard
  ceiling of ~73 Ollama searches/day — the catalogue is structurally
  over-subscribed on one laptop; a "slow day" is invisible until Ashok asks.
Build: a daily coverage tracker (roles run / roles enabled, jobs caught,
time lost to heat pause / deploys / enrichment) + an alert when the day is
falling behind pace by noon. Emit `browser_open` from enrichment sessions
too.

### 21. Fix the 4/135 coverage hole — reach the ~73 searches/day ceiling

Ashok (2026-08-06): parked in backlog for iteration planning. Yesterday the
tower ran only 4 of 135 enabled role searches (3% coverage) against a
measured capacity of ~73/day. Work: confirm the dominant cause from the live
ThinkPad console (heat pause vs deploy cancels vs worker contention vs cron
shadow), then fix in that order — e.g. retrigger roles cancelled by deploys,
make enrichment yield to due searches, and re-slot roles whose daily cron
window was shadowed after reseed. Related: #20 gives the monitoring so a slow
day is visible by noon; #19 puts "Coverage today: N/135" on `/health`.
Structural decision for planning: 135 roles > 73/day ceiling on one laptop —
trim the catalogue, accept a 2-day rotation, or add the second laptop.

### 22. Result-refinement buttons — time window + enrichment-powered filters

Ashok (2026-08-06): after the first result set (with links) is shown, offer
button filters so the guest can refine without typing.

**Slice A — time chips:** `24h · 2 days · 7 days · This month` under the
results. Gap found in investigation: `/api/jobs` (the list endpoint the
button flow uses) has no `days`/window param today — only exact
`posted_date`. Add a `days` filter (on `posted_date`, falling back to
`scraped_at` for unenriched rows) mirroring the insights endpoint's
`days in (0,1,2,4,7,14,30)` contract.

**Slice B — enrichment chips:** the requirements backfill already stores,
per job: experience band + min/max years, seniority level, degrees (B.Tech,
MBA, Diploma…), certifications (AWS, Azure, CEH, ISTQB… ~18 curated),
domains (Banking, FinTech, Healthcare, SaaS, AI/ML… 19), real posted date,
and company profile bits (logo, tagline, punchline, followers, size). Expose
`degree` / `certification` / `domain` as `/api/jobs` filters, then surface
the 2–3 most discriminating as button rows (e.g. Degree, Certification)
while browsing results. Honesty rule: these filters only see enriched rows —
show "of enriched jobs" counts, never pretend full coverage while the
backfill queue is pending.

Keeps every fact deterministic (API-filtered rows only); buttons follow the
existing `ButtonFlow` grammar. Depends on nothing else in the backlog;
pairs naturally with #15 Job Alerts (same filter vocabulary for alert
subscriptions).

### 23. Job cards — one message per job, Apply + More info buttons (kill the link wall)

Ashok (2026-08-06): today's results are one text block where raw LinkedIn
URLs make the list unreadable. Redesign: each job = its own message card.

**Card layout (per job, separate message):**
```
Machine Learning Engineer
Infosys · Bengaluru · 1–2 years
[ Apply ]  [ More info ]
```
- **Apply** = Telegram inline URL button embedding the canonical LinkedIn
  link — no naked URL in the text at all. (URL buttons need no callback;
  guests jump straight to LinkedIn.)
- **More info** = callback button (carries the job id) that reveals the
  enrichment harvest for that job: company tagline/punchline, follower
  count, employee size, degrees, certifications, domains, real posted date.
  Only enriched fields are shown; missing fields are omitted, never invented.
- Company logo (enrichment `logo_url`) can ride as the card's photo in a
  later slice (`sendPhoto` + caption).

**Batch + pagination:** send ~5 cards per page (not 10) to respect
Telegram's ~1 msg/sec per-chat pacing and keep the thread scannable, then a
final summary message with `[ More jobs ]` (replaces typing "more"),
plus the #22 refinement chips (time window / degree / cert / domain) on the
same summary message — one navigation hub under each result page.

**Grounding rules unchanged:** card text is deterministically formatted from
API rows; callbacks resolve by job id from the tower — the model never
authors any card content. Pairs with #22 (filters live on the summary hub)
and #15 (alert opt-in button can join the hub later).

### 10. Move Telegram session/guest state off SQLite onto Postgres+Redis (1 lakh-guest scale)

**Standing target (Ashok, 2026-08-05):** JobMaster must be designed to serve
1,00,000 (1 lakh) users/guests in a month; every infra/logic choice from here
should be picked with that scale in mind. Full research + rationale in
[`documents/scale-and-memory-architecture.md`](./scale-and-memory-architecture.md).

**Problem:** `job_engine/app/telegram_sessions.py` (search sessions,
onboarding state, guest profiles, conversation history, the inbox queue) is
one local SQLite file. SQLite single-writer file locking and single-machine
storage are fine for the current pilot but become the ceiling well before 1
lakh monthly guests — and they block ever running more than one JobMaster
poller process.

**Approach (not started):**
1. Move those SQLite tables into Postgres (schema/access patterns unchanged
   — a storage swap, not a redesign).
2. Move the per-chat "processing now" lock and rate limiting into Redis
   (already provisioned for Celery) instead of an in-process
   `threading.Lock()`.
3. Once state is off a local file, allow more than one JobMaster poller
   process — keep the existing FIFO/no-duplicate-poller contract
   (`JM-125`/`JM-126` in the validation doc).
4. Add a synthetic load test (k6/locust-style burst) against the dedicated
   JobMaster service — there is currently zero load evidence.

**Acceptance:** documented capacity number (e.g. "N sustained req/s / M
concurrent chats on current hardware") replaces "we think SQLite is fine";
FIFO-per-chat and no-cross-chat-leakage contracts still hold after the
migration; existing `job_engine/tests/test_jobmaster_*.py` suite still green
against the new backing store.

**Files:** `job_engine/app/telegram_sessions.py`, `docker-compose.yml`,
`job_engine/scripts/telegram_job_bot.py`, deploy scripts.

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
