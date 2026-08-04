"""Deploy verification — lets Akay (Cursor cloud) or Ashok confirm that a PR
merged to `main` actually landed on the ThinkPad runtime.

`scripts/deploy_local.sh` (run by the `Deploy ThinkPad` GitHub Action on the
self-hosted runner) writes a small JSON stamp after every deploy attempt.
This module just reads that stamp and cross-checks it against the commit the
running process tree is actually built from, so the API can answer
"what is live right now?" without any auth or DB access.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

# Computed independently of app.config (no dotenv/DB import needed for a
# read-only file+git check).
BASE_DIR = Path(__file__).resolve().parent.parent
STAMP_FILE = BASE_DIR / '.data' / 'last_deploy.json'


def _git_head() -> str | None:
    """Best-effort `git rev-parse HEAD` of the running working tree."""
    try:
        out = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=str(BASE_DIR.parent),
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def compute_deploy_status() -> dict:
    stamp: dict = {}
    if STAMP_FILE.is_file():
        try:
            stamp = json.loads(STAMP_FILE.read_text(encoding='utf-8'))
        except Exception:
            stamp = {'error': 'last_deploy.json is unreadable/corrupt'}

    # Captured when the API process starts. Falling back to git is only for
    # local development; production units always set this immutable value.
    running_sha = os.getenv('WATCH_TOWER_RUNTIME_SHA') or _git_head()
    deployed_sha = stamp.get('sha')

    return {
        'deployed_sha': deployed_sha,
        'deployed_at': stamp.get('deployed_at'),
        'before_sha': stamp.get('before_sha'),
        'status': stamp.get('status'),
        'policy': stamp.get('policy'),
        'running_sha': running_sha,
        # True only when we have both shas and they agree — the one number
        # Akay should check after every PR merge.
        'in_sync': bool(deployed_sha) and bool(running_sha) and deployed_sha == running_sha,
        'stamp_found': bool(stamp),
    }
