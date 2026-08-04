# Milestone — JobMaster Gate 3.0 capability #1

| Field | Value |
|---|---|
| Date | 2026-08-04 |
| Label | `milestone/jobmaster-gate3-v1` |
| Git tip at lock | `main` @ `2fda2d7` |
| Acceptance | Ashok, after Supriya's live Telegram test: **"It's definitely better, lock this and let's develop from here."** |

## What is locked

- Telegram uses the dedicated JobMaster long-polling service; Hermes does not
  consume Telegram updates.
- Every user gets the same JobMaster persona and capability boundary.
- Messages receive an immediate `Thinking…` acknowledgement.
- Natural language is reduced to validated role, city, experience, time-window,
  and insight intent.
- Job replies contain up to 10 grounded rows with canonical LinkedIn links;
  `more` paginates without duplicates and `/new` resets cleanly.
- Counts, rankings, comparisons, and trends come from Watch Tower facts.
- Models never author jobs, links, companies, experience, or market numbers.
- Durable per-chat state, FIFO handling, bounded delivery retries, runtime-SHA
  verification, and deployment rollback guard the production path.

## Why this supersedes Eureka

`milestone/eureka-telegram-bot` proved that the tower could be reached through
Telegram. This milestone locks the first user-accepted JobMaster product
contract after removing the unreliable Hermes interception path and malformed
model-authored replies.

## Development rule

Build subscriptions, ATS resume support, preparation guides, projects, quizzes,
flashcards, news, tutorials, and LMS progress as additive capabilities behind
the same conversation boundary. Do not restore Hermes Telegram fallback or let
a model become the source of job-market facts.

## Recovery

```bash
cd /home/user/Documents
git status
git switch -c recover/jobmaster-gate3-v1 milestone/jobmaster-gate3-v1
```

Do not use destructive Git commands to recover.
