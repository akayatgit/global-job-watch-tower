# Deploy verification — is a merged PR actually live on the ThinkPad?

**Why this exists:** Cursor cloud agents (Akay) have no network path into the
ThinkPad. A PR merging to `main` and the self-hosted "Deploy ThinkPad" GitHub
Action running are the *only* way code reaches the runtime — so after every
push to `main`, run the check below before telling Ashok a feature is live.

## Incident that forced this (2026-08-02 → 2026-08-04)

Three consecutive `Deploy ThinkPad` runs failed back-to-back:

| Run | When | Reason |
|---|---|---|
| `30787862166` | 2026-08-03 05:41 | `documents/briefs/latest.txt` dirty |
| `30819699561` | 2026-08-03 13:48 | `documents/briefs/latest.txt` dirty |
| `30880788706` | 2026-08-04 05:28 | `documents/briefs/latest.txt` dirty |

`job_engine/scripts/hermes_daily_brief.py` (cron) overwrites
`documents/briefs/latest.txt` on every run, but that file was accidentally
git-tracked. `scripts/deploy_local.sh` refuses to deploy over a dirty tracked
file (correct instinct — protects real local edits) — but the check ran
**before** `git fetch`/`reset`, so the very commit that would have fixed it
could never be pulled. The ThinkPad was silently stuck 3 pushes behind for
~2 days with every deploy failing red in GitHub Actions the whole time, and
nobody was watching that signal.

**Fix (this change):**

1. `documents/briefs/` added to `.gitignore` and untracked — it is
   cron-regenerated output, not source, exactly like `job_engine/.data/`.
2. `scripts/deploy_local.sh`'s dirty-tree gate now excludes
   `documents/briefs/` (`git status -- . ':!documents/briefs'`) and discards
   any drift there before pulling, so this specific class of self-inflicted
   wedge cannot recur even if some other cron writes into a tracked path.
3. `scripts/deploy_local.sh` now warns (non-fatal) if the deployed commit
   doesn't match `$GITHUB_SHA` — catches double-push races.

## The check — run this after every PR merges to `main`

```bash
scripts/check_thinkpad_deploy.sh            # checks origin/main HEAD
scripts/check_thinkpad_deploy.sh <sha>      # checks a specific commit
```

It does two independent checks and passes if either confirms deployment:

1. **GitHub Actions** (works from Cursor cloud — `gh` is available there):
   finds the `Deploy ThinkPad` run for that exact commit via
   `gh run list --workflow deploy-thinkpad.yml` and checks
   `status=completed conclusion=success`. This is the check Akay should run
   from a cloud agent session — it needs no access to the ThinkPad.
2. **Live endpoint** (only reachable from the ThinkPad's LAN, or the public
   tunnel once Cloudflare Access is confirmed — see
   [`remote-access-cloudflare.md`](./remote-access-cloudflare.md)):
   `GET /api/deploy/status` on the running app, compared to the target sha.
   ```bash
   TOWER_STATUS_URL=http://127.0.0.1:8001 scripts/check_thinkpad_deploy.sh
   ```

Exit code `0` = deployed. Non-zero = not deployed / mismatched / the deploy
run failed — the script prints which, and the `gh run view --log <id>`
command to read why.

## `/api/deploy/status` contract

No auth, no DB — safe to poll. Backed by
`job_engine/app/deploy_status.py`, which reads the stamp
`scripts/deploy_local.sh` writes to `job_engine/.data/last_deploy.json`
after every deploy attempt, and cross-checks it against the commit the
running process was actually started from (`git rev-parse HEAD` in the
working tree).

```json
{
  "deployed_sha": "9616806f...",
  "deployed_at": "2026-08-04T05:58:29+00:00",
  "before_sha": "558cf25c...",
  "status": "ok",
  "policy": "cancel-active-then-retrigger",
  "running_sha": "9616806f...",
  "in_sync": true,
  "stamp_found": true
}
```

`in_sync: false` (or `stamp_found: false` on a fresh box before the first
deploy stamp exists) means the last deploy attempt and the running process
disagree — treat as **not deployed**.

## Standing checklist (append to your PR-merge muscle memory)

1. Merge the PR to `main`.
2. Wait for the push to land (the Action fires on `push: branches: [main]`).
3. Run `scripts/check_thinkpad_deploy.sh` (from Cursor cloud, this is the
   `gh`-only path — no `TOWER_STATUS_URL` needed).
4. If it reports **NOT deployed**, read the failure log
   (`gh run view --log <run-id>`) before telling Ashok anything shipped.
5. If deploys are failing for a *systemic* reason (like the briefs incident
   above), fix the root cause in the same PR or a fast follow — don't just
   re-run and move on, or the ThinkPad silently drifts behind again.
