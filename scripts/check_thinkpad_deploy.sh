#!/usr/bin/env bash
# Confirm a commit that just merged to main actually landed on the ThinkPad.
#
# Two independent checks (either alone is useful, together is conclusive):
#   1. GitHub: did the self-hosted "Deploy ThinkPad" Action run and succeed
#      for that commit? (works from anywhere with `gh` — including Cursor
#      cloud agents, which have no network path to the ThinkPad itself.)
#   2. Live endpoint: does the running app report that exact commit as its
#      deployed sha? (only reachable from the ThinkPad's LAN, or from a
#      browser once Cloudflare Access is confirmed for the public tunnel —
#      see documents/remote-access-cloudflare.md.)
#
# Usage:
#   scripts/check_thinkpad_deploy.sh                # checks origin/main HEAD
#   scripts/check_thinkpad_deploy.sh <sha-or-ref>    # checks a specific commit
#   TOWER_STATUS_URL=http://127.0.0.1:8001 scripts/check_thinkpad_deploy.sh
#
# Exit code 0 = deployed & in sync. Non-zero = not deployed yet / mismatch /
# deploy failed — read the printed reason.
set -euo pipefail

WORKFLOW="deploy-thinkpad.yml"
REF="${1:-origin/main}"

if ! command -v gh >/dev/null 2>&1; then
  echo "check_thinkpad_deploy: 'gh' CLI not found — cannot check GitHub Actions." >&2
  exit 2
fi

echo "== resolving target commit ($REF) =="
git fetch origin main --quiet 2>/dev/null || true
TARGET_SHA="$(git rev-parse --verify "${REF}^{commit}" 2>/dev/null || true)"
if [ -z "$TARGET_SHA" ]; then
  echo "could not resolve '$REF' to a commit — pass a valid ref/sha." >&2
  exit 2
fi
echo "target commit: $TARGET_SHA"

echo
echo "== GitHub Actions: $WORKFLOW =="
RUN_JSON="$(gh run list --workflow "$WORKFLOW" --limit 20 \
  --json headSha,status,conclusion,url,createdAt,displayTitle 2>/dev/null || echo '[]')"

RUN_ROW="$(echo "$RUN_JSON" | python3 -c "
import json, sys
target = sys.argv[1]
rows = json.load(sys.stdin)
for r in rows:
    if r.get('headSha') == target:
        print(json.dumps(r))
        break
" "$TARGET_SHA" || true)"

GH_OK=1
if [ -z "$RUN_ROW" ]; then
  echo "NO 'Deploy ThinkPad' run found yet for $TARGET_SHA."
  echo "   (either the push hasn't triggered it, the runner is offline, or it hasn't reached this commit yet)"
  GH_OK=0
else
  STATUS="$(echo "$RUN_ROW" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("status"))')"
  CONCLUSION="$(echo "$RUN_ROW" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("conclusion"))')"
  URL="$(echo "$RUN_ROW" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("url"))')"
  echo "run status=$STATUS conclusion=$CONCLUSION"
  echo "$URL"
  if [ "$STATUS" = "completed" ] && [ "$CONCLUSION" = "success" ]; then
    echo "GitHub Actions confirms this commit deployed successfully."
  else
    echo "Deploy run did NOT succeed for this commit — read the log:"
    echo "   gh run view --log $(echo "$RUN_ROW" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("url").rsplit("/",1)[-1])' 2>/dev/null || true)"
    GH_OK=0
  fi
fi

STATUS_URL="${TOWER_STATUS_URL:-}"
LIVE_OK=""
if [ -n "$STATUS_URL" ]; then
  echo
  echo "== live endpoint: $STATUS_URL/api/deploy/status =="
  BODY="$(curl -fsS --max-time 5 "$STATUS_URL/api/deploy/status" 2>/dev/null || true)"
  if [ -z "$BODY" ]; then
    echo "could not reach $STATUS_URL/api/deploy/status"
    LIVE_OK=0
  else
    echo "$BODY"
    LIVE_SHA="$(echo "$BODY" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("deployed_sha") or "")' 2>/dev/null || true)"
    if [ "$LIVE_SHA" = "$TARGET_SHA" ]; then
      echo "live app reports the exact target commit as deployed."
      LIVE_OK=1
    else
      echo "live app reports a different sha ($LIVE_SHA) — not yet deployed."
      LIVE_OK=0
    fi
  fi
fi

echo
if [ "$GH_OK" = "1" ] || [ "${LIVE_OK:-0}" = "1" ]; then
  echo "RESULT: $TARGET_SHA is deployed to the ThinkPad."
  exit 0
else
  echo "RESULT: $TARGET_SHA is NOT confirmed deployed to the ThinkPad."
  exit 1
fi
