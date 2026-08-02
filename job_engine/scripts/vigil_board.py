#!/usr/bin/env python3
"""Print a VIGIL board as plain text (Telegram / Hermes quick_commands).

Usage:
  vigil_board.py tower|health|signals|searches|watchlist|fresh|brief|help
  vigil_board.py signals 0
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.vigil_boards import render_board  # noqa: E402


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ('-h', '--help'):
        print(render_board('help'))
        return 0
    board = argv[0]
    days = None
    if len(argv) > 1:
        try:
            days = int(argv[1])
        except ValueError:
            days = None
    print(render_board(board, days=days))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
