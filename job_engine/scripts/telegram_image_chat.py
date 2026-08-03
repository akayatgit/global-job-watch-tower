#!/usr/bin/env python3
"""Hermes Telegram entry: image-only replies via Replicate.

- Word \"Carousel\" → professional TECH JOB MARKET MOVEMENT album
- Anything else → goofy Tanglish meme photo (no Telegram text caption)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    sys.path.insert(0, str(ROOT / 'scripts'))
    from telegram_watch_tower import cmd_image_chat  # noqa: WPS433

    msg = ' '.join(sys.argv[1:]).strip()
    if not msg and not sys.stdin.isatty():
        msg = sys.stdin.read().strip()
    if not msg:
        print('usage: telegram_image_chat.py <user message>', file=sys.stderr)
        return 2
    return cmd_image_chat(msg)


if __name__ == '__main__':
    raise SystemExit(main())
