"""Build/version counter — bumped by scripts/bump_version.sh on every push.

VIGIL shows this at the bottom of the left module rail and recolors the
orb's particle "dots" from it, so a new deploy is visible at a glance
without reading logs. See documents/deploy-verification.md.
"""

from __future__ import annotations

from pathlib import Path

# job_engine/app/version_info.py -> job_engine -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = _REPO_ROOT / 'VERSION'


def get_version() -> int:
    try:
        return int(VERSION_FILE.read_text(encoding='utf-8').strip())
    except Exception:
        return 0
