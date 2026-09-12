# Prompt Tower — Telegram validation

This file used to hold a seeker-chat corpus. **Product is Prompt Tower.**

Stable checks going forward:

| ID | Action | Expected |
|---|---|---|
| PT-001 | Any user `/igtovid` | `Now Paste the link.` |
| PT-002 | Any user `/pintovid` | Same one-liner |
| PT-003 | Paste a Pinterest pin URL | `Whats the hook?` |
| PT-004 | Paste an Instagram reel URL | `Whats the hook?` |
| PT-005 | `/start` · `/help` · hi | Same reverse ask — never an essay |
| PT-006 | Whole thread | No `Thinking…`, no hiring-site links, no seeker copy |

Owner still has `/prompts` · `/health` · access · `/push`.
