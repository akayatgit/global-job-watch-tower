# Prompt Tower — Product Requirements Document

| Field | Value |
|---|---|
| **Product** | Prompt Tower |
| **Tagline** | Reverse any Instagram reel or Pinterest pin into a cinematic video prompt — then render it |
| **Powered by** | Quanta HR Labs |
| **Document** | Product Requirements — Prompt application (overwrites the old collector PRD) |
| **Status** | Live product — Ashok 2026-09-12: every user runs `/igtovid` · `/pintovid` |
| **Stakeholders** | Ashok (Vision Owner / Yes–No Authority) · Akay (AI Lead — full build agency) |
| **North star** | Daily top-10 D2C video prompts + public reverse workflows. Instagram authority first, then prompt + video packs sell |
| **Source safety (absolute)** | **First priority above all features:** local git must keep source recoverable |
| **HARD LOCK (Ashok 2026-09-12)** | This is a **Prompt application**. Telegram, docs, and user-facing copy never mention catalogue hunting, seeker boards, or third-party hiring sites. Users get `/igtovid` and `/pintovid` only |
| **Spec** | [`documents/prompt-tower.md`](prompt-tower.md) |
| **Runtime home** | **Lenovo ThinkPad P16 Gen 1 · Ubuntu 24.04 LTS · local-only** — API `127.0.0.1:8001`, Postgres `:5433`, Redis `:6379`, Celery worker+beat, Ollama |
| **Remote UI** | `https://tower.jobmaster.agency` → ThinkPad `127.0.0.1:8001` (Cloudflare Tunnel + Access) |
| **Remote source + auto-deploy** | Public GitHub [akayatgit/global-job-watch-tower](https://github.com/akayatgit/global-job-watch-tower). Merge/push to `main` deploys on the ThinkPad |

---

## 0. What the product is

Prompt Tower has two public workflows and one owner deck.

| Surface | Who | What |
|---|---|---|
| `/igtovid` | **Every user** | Reverse an Instagram reel into a timestamped generation prompt |
| `/pintovid` | **Every user** | Reverse a Pinterest pin the same way |
| Paste a reel / pin URL | **Every user** | Same intake — `Whats the hook?` → twist → model → `Workflow Started…` |
| `/prompts` · `/promptscan` · `/addprompt` | Owner | Daily top-10 D2C prompts, score, photo → video |
| VIGIL | Owner | Collection cockpit on the ThinkPad |

Public Telegram copy is one line at a time:

1. `Now Paste the link.`
2. `Whats the hook?`
3. `Shall we twist the video?`
4. `Select a Prompt Model…`
5. `processing..` / `Workflow Started…`

Never send essays. Never send `Thinking…`. Prompts stay **under 3000 characters**.

---

## 0A. Source safety (absolute — before features)

Ashok’s vision lives in this codebase. **Akay’s first duty is to keep source recoverable.**

| Rule | Practice |
|---|---|
| Local git | Repo root: `/home/user/Documents` |
| Remote git | Public: `https://github.com/akayatgit/global-job-watch-tower` (`origin` → `main`) |
| Never commit | `.env`, passwords, `job_engine/.data/`, browser profiles |
| Do commit | `job_engine/app`, migrations, templates, `documents/`, shared Cursor rules, `.env.example` |
| Standing rule | `.cursor/rules/source-safety.mdc` (always apply) |
| Failure mode | If source is lost/corrupted, stop feature work and restore from git first |

### 0A.1 Remote develop → ThinkPad deploy (2026-08-01)

Ashok can build from phone or any device: open a PR → merge to `main` → this laptop redeploys.

| Piece | Detail |
|---|---|
| Trigger | GitHub Actions on **push to `main` only** (never on open PRs/forks — public-repo safety) |
| Runner | Self-hosted under `/home/user/actions-runner`, labels `self-hosted,linux,watch-tower`, systemd service |
| Deploy script | [`scripts/deploy_local.sh`](../scripts/deploy_local.sh) — flock, pause beat → stop worker → `git reset --hard origin/main` → `alembic upgrade head` → [`job_engine/restart_app.sh`](../job_engine/restart_app.sh) |
| Survives deploy | Postgres/Redis data, `.env`, Chrome session, Ollama |
| Restarts | API `:8001`, Celery worker, Celery beat |
| Stamp / logs | `job_engine/.data/last_deploy.json`, `job_engine/.data/logs/deploy.log` |

**Mobile path:** GitHub app → branch → PR → merge → watch Actions on the ThinkPad runner → tower comes back on new SHA.

### 0A.3 Remote browser access — Cloudflare Tunnel + Access

| Piece | Detail |
|---|---|
| Public URL | **https://tower.jobmaster.agency** |
| Origin | `http://127.0.0.1:8001` — loopback only |
| Access | Allow email `ashokofficial55@gmail.com` — verify Incognito OTP before sharing |
| Ops doc | [`documents/remote-access-cloudflare.md`](remote-access-cloudflare.md) |

---

## 1. Users

| Person | What they can do |
|---|---|
| Anyone who texts the bot | `/igtovid` · `/pintovid` · `/start` · `/help` · paste an Instagram or Pinterest link · send a clip |
| Ashok (owner chat) | All of the above + `/prompts` deck, scan, stats, access control, `/push`, `/health` |

Blocked senders stay blocked. Everyone else is in the moment they say hi.

---

## 2. Base system we keep

The ThinkPad stack stays: Telegram ingress, Celery, Postgres, Redis, VIGIL, Cloudflare tunnel, deploy script. Folder name `job_engine/` is historical. New work is Prompt Tower only (`app/prompts/`, `app/telegram_prompts.py`, partner asset API).

---

## 3. Selling law

Trust first: every user gets a working reverse workflow. Later the same channel can carry prompt + video packs. Never spam. Never let a user feel ignored — acknowledge with the next one-liner, not an essay.

---

## 4. Out of scope

User-facing catalogue hunting, seeker boards, hiring-site scrapes on Telegram, and any copy that talks about openings or applicants. Those paths are disconnected. Do not re-wire them without Ashok's explicit word.
