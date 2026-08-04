#!/usr/bin/env bash
# Bump the top-level VERSION counter and commit it on its own, small commit.
#
# Run this once right before every push (per standing instruction: every push
# gets its own version-bump commit). The running app reads VERSION and shows
# it at the bottom of the VIGIL left module rail, and recolors the orb's
# particle "dots" from it — a quick, at-a-glance signal that new code landed.
#
# Usage: scripts/bump_version.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

VERSION_FILE="VERSION"
CUR="$(cat "$VERSION_FILE" 2>/dev/null || echo 0)"
CUR="${CUR//[^0-9]/}"
[ -z "$CUR" ] && CUR=0
NEXT=$((CUR + 1))

echo "$NEXT" > "$VERSION_FILE"
git add "$VERSION_FILE"
git commit -m "Bump version to v${NEXT}"
echo "bumped VERSION: v${CUR} -> v${NEXT}"
