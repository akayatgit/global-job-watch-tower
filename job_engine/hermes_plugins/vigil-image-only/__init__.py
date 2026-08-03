"""COURIER gate: forward Telegram text to DIRECTOR (OpenAI), skip Hermes Ollama chat."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path

logger = logging.getLogger("vigil-image-only")

PY = "/home/user/anaconda3/envs/ai/bin/python"
ROOT = "/home/user/Documents/job_engine"
JE_ENV = Path(ROOT) / ".env"


def _platform_name(event) -> str:
    src = getattr(event, "source", None)
    plat = getattr(src, "platform", None) if src else None
    if plat is None:
        return ""
    return getattr(plat, "value", str(plat)).lower()


def _is_telegram(event) -> bool:
    return _platform_name(event) in {"telegram", "tg"}


def _bot_username(event) -> str:
    state = Path.home() / ".hermes" / "watch_tower_telegram.json"
    if state.exists():
        try:
            import json
            data = json.loads(state.read_text())
            if data.get("username"):
                return str(data["username"])
        except Exception:
            pass
    return "vigil_akay_bot"


def _chat_id(event) -> str:
    src = getattr(event, "source", None)
    if src is not None and getattr(src, "chat_id", None):
        return str(src.chat_id)
    # Fallback: home channel so DIRECTOR never runs with empty chat
    hermes_env = Path.home() / ".hermes" / ".env"
    if hermes_env.exists():
        for ln in hermes_env.read_text().splitlines():
            if ln.startswith("TELEGRAM_HOME_CHANNEL="):
                return ln.split("=", 1)[1].strip()
    return ""


def _director_env() -> dict:
    """Child env with job_engine secrets forced (override Hermes dummy OPENAI keys)."""
    env = os.environ.copy()
    if JE_ENV.exists():
        for ln in JE_ENV.read_text().splitlines():
            if not ln or ln.lstrip().startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k in {
                "OPENAI_API_KEY",
                "OPENAI_BRAIN_MODEL",
                "REPLICATE_API_TOKEN",
                "REPLICATE_MODEL",
            }:
                env[k] = v
    # Avoid hermes venv confusing child tooling
    env.pop("VIRTUAL_ENV", None)
    env["PYTHONPATH"] = ROOT
    return env


def _run_director(text: str, bot: str, chat: str) -> None:
    try:
        cmd = [
            PY, "-m", "app.director.router",
            "--bot", bot,
            "--chat", chat,
            "--text", text,
        ]
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=ROOT,
            env=_director_env(),
        )
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        # Always surface stderr — rescue used to hide real failures
        if err:
            logger.info("DIRECTOR stderr: %s", err[-1200:])
        if r.returncode != 0:
            logger.error(
                "DIRECTOR failed rc=%s stdout=%s stderr=%s",
                r.returncode,
                out[:200],
                err[-800:],
            )
        else:
            logger.info("DIRECTOR ok: %s", out[:160] or "(empty stdout)")
    except Exception as e:
        logger.exception("DIRECTOR exception: %s", e)


def telegram_to_director(event, gateway=None, session_store=None, **kwargs):
    if not _is_telegram(event):
        return None

    text = (getattr(event, "text", None) or "").strip()
    if not text:
        return {"action": "skip", "reason": "telegram-empty"}

    bot = _bot_username(event)
    chat = _chat_id(event)
    logger.info("DIRECTOR dispatch bot=%s chat=%s text=%s", bot, chat, text[:120])
    t = threading.Thread(target=_run_director, args=(text, bot, chat), daemon=True)
    t.start()
    t.join(timeout=600)

    return {"action": "skip", "reason": "director-handled"}


def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", telegram_to_director)
    logger.info("DIRECTOR gate armed — Telegram text-first (chat /summarize /image)")
