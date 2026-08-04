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

---

## To Do

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

## Done

| Card | PR | Date |
|---|---|---|
| Deploy verification check + fix `documents/briefs` dirty-file wedge (attempt 1 — insufficient alone) | [#5](https://github.com/akayatgit/global-job-watch-tower/pull/5) | 2026-08-04 |
| Build version counter + orb dot-color signal + rail version footer | [#6](https://github.com/akayatgit/global-job-watch-tower/pull/6) | 2026-08-04 |
| Actually unblock the deploy pipeline (fix lives in workflow YAML, not the gated script) | [#7](https://github.com/akayatgit/global-job-watch-tower/pull/7) | 2026-08-04 |
| **#1 [URGENT] Telegram guest access** — own allowlist (`/allow` `/revoke` `/allowuser` `/revokeuser` `/guests`, expiry, owner can't be revoked), deploy owns the Hermes gateway + plugin sync, sender-scoped replies, guest persona → deterministic zero-LLM guest replies, outer exception guard so a bug can never fall through to Hermes' built-in agent. Full incident + fix write-up lives in `documents/hermes-agent-integration.md` § "Telegram guest access" — do not re-investigate, it is closed. | [#19](https://github.com/akayatgit/global-job-watch-tower/pull/19) · [#20](https://github.com/akayatgit/global-job-watch-tower/pull/20) · [#21](https://github.com/akayatgit/global-job-watch-tower/pull/21) · [#22](https://github.com/akayatgit/global-job-watch-tower/pull/22) · [#23](https://github.com/akayatgit/global-job-watch-tower/pull/23) · [#24](https://github.com/akayatgit/global-job-watch-tower/pull/24) · [#25](https://github.com/akayatgit/global-job-watch-tower/pull/25) · [#26](https://github.com/akayatgit/global-job-watch-tower/pull/26) | 2026-08-04 |

**Note on stale duplicate PRs — ignore, do not resume:** draft `#9`
(`cursor/telegram-guest-access-624b`, based on the never-merged `#8`
`cursor/add-engineering-kanban-624b`) and its child `#10`
(`cursor/telegram-allow-username-azr0099-fb06`) built card #1 a different way,
earlier, before the real fix above landed directly on `main`. Left open per
"don't close PRs without Ashok's word," but they are dead branches — the
shipped code is `job_engine/app/telegram_guests.py` on `main`, not either of
those branches.
