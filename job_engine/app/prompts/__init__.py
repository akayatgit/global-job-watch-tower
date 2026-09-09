"""Prompt Tower — AI video prompts for D2C product videos (pivot 2026-09-09).

Pipeline: sources → normalize/dedupe → RAG → Hermes scoring → daily top-10
→ Telegram (owner) → approve + product image → video creator → assets.
"""
