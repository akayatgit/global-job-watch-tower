#!/usr/bin/env python3
"""TECH JOB MARKET MOVEMENT — generate + send carousel to Telegram.

Hermes quick_command /carousel and CLI both land here.
Delivery surface = Telegram only (no local gallery for Ashok).
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[1]


def main() -> int:
    # Reuse telegram helper (token from ~/.hermes/.env)
    sys.path.insert(0, str(ROOT / 'scripts'))
    from telegram_watch_tower import cmd_send_carousel  # noqa: WPS433

    return cmd_send_carousel()


if __name__ == '__main__':
    raise SystemExit(main())
