# Scale target and session-memory architecture

**Standing target (set by Ashok, 2026-08-05):** JobMaster must be designed to
serve **1,00,000 (1 lakh) users/guests within a month**, and the scraped job
data must reach roughly that many people through real conversion — not just
sit in Postgres. Every infra/logic decision from here on should be picked
with "does this hold at 1 lakh concurrent-ish users" in mind, not "does this
work for the 5 test guests we have today."

This document answers three things Ashok asked directly:

1. Does our existing infra (Hermes / the agentic system) already have
   conversation-session memory?
2. What should we use to remember a guest across visits and welcome them
   back with zero friction — build it ourselves, or adopt something with
   real GitHub traction that's free and self-hostable?
3. What does "always think of 1 lakh people" mean concretely for how we
   build JobMaster from here?

## 1. What we already have

| Component | What it stores | Who reads it | Backing store | Shape |
|---|---|---|---|---|
| `app/director/sessions.py` (`SQLiteSession` from the `openai-agents` SDK) | Raw conversation turns, replayed to the LLM as context | DIRECTOR (Ashok's Jarvis chat — image/carousel workflows) | One local SQLite file | Framework-managed, LLM re-reads full history every turn |
| `app/telegram_sessions.py` → `conversation_history` | Last 40 delivered guest question/reply pairs per chat | `/history` (Ashok-only) | Local SQLite file (`jobmaster_telegram.db`) | Raw pairs, deterministic |
| `app/telegram_sessions.py` → `guest_profiles` **(new, 2026-08-05)** | Distilled role/experience/city + last-updated, refreshed by any completed role-scoped search | `/guestprofile` (Ashok-only) + JobMaster's own "welcome back" greeting | Same local SQLite file | Structured summary, deterministic — no LLM ever writes to it |

**So yes — the "agentic system" (OpenAI Agents SDK) already ships a memory
primitive (`SQLiteSession`), and we already use it, but only for DIRECTOR's
own Jarvis-style chat with Ashok.** It was never wired into JobMaster, and it
shouldn't be used there as-is:

- `SQLiteSession` replays raw history back into an LLM prompt. JobMaster's
  hard rule is that **no LLM ever authors a guest-facing job fact** — replaying
  raw history into a model and letting it "recall" a guest's preference is
  exactly the hallucination shape we killed twice already (guest-soul v1 →
  v2, 2026-08-04). A model could paraphrase "AI Engineer in Chennai" into
  "AI/ML roles across Tamil Nadu" and nobody would notice until a wrong
  answer ships.
- It's one SQLite file — same scaling ceiling as our own tables (see §3).

**What we built this session (`guest_profiles`) is the right shape for
JobMaster**: a small set of structured fields (role_family, role_keywords,
experience, city, updated_at), written by deterministic code paths only,
read back through a plain template ("Welcome back! ... you were looking for
X in Y. Reply 'yes' for today's openings, or tell me a new role.") — never
through an LLM. This is now live: any completed search (onboarding or
direct) updates it, and a returning guest's next greeting recalls it with a
one-word zero-friction repeat. See `documents/kanban.md` card #9 and
`documents/jobmaster-telegram-validation.md` JM-130..147.

## 2. What the open-source ecosystem offers (researched 2026-08-05)

For teams that want an LLM to *extract and manage* memories automatically
(not just recall stored facts — genuinely useful for DIRECTOR's Jarvis chat,
which is allowed to reason/converse, unlike JobMaster):

| Project | License | Self-host | GitHub stars (approx.) | Shape | Fit for us |
|---|---|---|---|---|---|
| **Mem0** (`mem0ai/mem0`) | Apache 2.0 | Yes, free | ~48–60k | Vector + lightweight graph memory, LLM auto-extracts facts from conversation, one API to store/recall | Best-fit if we ever want DIRECTOR (not JobMaster) to remember Ashok's preferences across sessions without hand-rolling it. Free self-hosted; the paid tiers only gate advanced graph features. |
| **Zep / Graphiti** (`getzep/graphiti`) | Apache 2.0 | Yes (needs Neo4j/FalkorDB/Kuzu) | ~24–28k | Temporal knowledge graph — tracks how facts change over time | Overkill for us today; the temporal-graph modeling shines for agents tracking evolving relationships, not a job-search bot with 3 fields. |
| **Letta** (formerly MemGPT) | Apache 2.0 | Yes, free | ~13–23k | Agent "manages its own memory" like an OS paging RAM/disk | Interesting for a long-horizon autonomous agent; more framework lock-in than we need. |
| **MemPalace** (`akarnokd/mempalace`) | MIT | Yes, always (SQLite, zero API calls) | New/small | Local entity-relationship memory, no cloud, no LLM calls required | Philosophically closest to what we already built (local, free, deterministic-capable) — worth a look if DIRECTOR's memory needs get more sophisticated, but too new/small to bet the product on yet. |

**Recommendation:** don't adopt any of these for JobMaster's guest-facing
memory — the deterministic `guest_profiles` table we already have is safer
(zero hallucination risk), free, and simpler to reason about for a 3-field
recall. If/when DIRECTOR's Jarvis chat wants genuine cross-session
personalization (not guest-facing, no verified-fact risk), **Mem0** is the
standout pick: largest ecosystem, Apache 2.0, truly free to self-host, and
it would layer on top of infra we may already stand up for Postgres (it can
use pgvector as its vector store — no new database engine required).

## 3. What "1 lakh users" actually changes

The memory *library* was never the bottleneck — the **datastore** is.
`job_engine/app/telegram_sessions.py` is a single local SQLite file
(`jobmaster_telegram.db`). SQLite is genuinely fine for the current pilot
scale, but it has hard limits that matter well before 1 lakh:

- **Single writer.** Every `INSERT`/`UPDATE` (a new message, a page turn, a
  profile refresh) takes an exclusive file lock. Under real concurrent load
  from many simultaneous chats, writes serialize and start queuing.
- **Single file, single machine.** It cannot be read/written from more than
  one process's disk at a time in a networked way — there is no path to
  running two JobMaster poller processes (or, eventually, one per city/shard)
  against the same session state without moving off SQLite first.
- **No connection pooling / no replicas** — no story for read scaling either.

Watch Tower already has the right pieces sitting unused for this purpose:
**Postgres** (system of record for jobs/companies) and **Redis** (already
provisioned for Celery). Both are free, self-hosted, already in
`docker-compose.yml`, and already proven at the scale a single ThinkPad can
serve. The concrete migration (not yet started — this is a plan, not a
completed slice):

1. Move `search_sessions`, `onboarding_sessions`, `guest_profiles`,
   `conversation_history`, and `telegram_inbox` from SQLite tables into
   Postgres tables (same schema, same access patterns — this is a storage
   swap, not a redesign).
2. Use Redis for the truly ephemeral, high-churn bits (per-chat "processing
   now" locks, rate-limit counters) instead of the in-process
   `threading.Lock()` + SQLite round-trip used today — this also removes the
   single-process assumption baked into the current lock.
3. Once state lives in Postgres/Redis instead of a local file, more than one
   JobMaster poller process can run safely (needed well before 1 lakh
   monthly guests generate enough concurrent Telegram traffic for one
   process to keep up) — see `documents/jobmaster-telegram-validation.md`
   JM-125/JM-126 for the FIFO/no-duplicate-poller contract this must keep.
4. Add basic load evidence (a k6/locust-style synthetic burst against the
   dedicated JobMaster service) before trusting any of this at real scale —
   we have zero load-test evidence today.

**Tracked as a new backlog card** (`documents/kanban.md` — "Move Telegram
session/guest state off SQLite onto Postgres+Redis for 1 lakh-guest scale")
rather than built in this pass: it touches migrations, `docker-compose.yml`,
and deploy scripts, and deserves its own reviewed slice rather than being
bundled into the onboarding feature.

## 4. Conversion, not just capacity

Ashok's second point — "the scraped data has to be distributed to around 1
lakh people through conversion" — is a distribution problem, not only an
infra one. Capacity work (§3) makes it *possible* to serve 1 lakh guests;
it does not by itself produce 1 lakh guests. That side of the flywheel is
already named in the roadmap as **"Map with Students" / TECH JOB MARKET
MOVEMENT** (social carousels, Tamil Nadu trendjack, a page students open) —
this document's job is only to make sure the product-side infra doesn't
become the ceiling once that distribution work starts working. Anyone
picking up growth/distribution work should read this section as the
capacity contract they're building against.
