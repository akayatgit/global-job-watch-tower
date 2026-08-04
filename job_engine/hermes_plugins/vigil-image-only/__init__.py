"""COURIER gate: forward Telegram text to DIRECTOR (OpenAI), skip Hermes Ollama chat.

Also enforces our own Telegram guest allowlist (documents/kanban.md card #1,
documents/hermes-agent-integration.md) so Ashok can grant/revoke access from
his phone via `/allow` `/revoke` `/guests` without any ThinkPad terminal
access. This requires `TELEGRAM_ALLOW_ALL_USERS=true` in `~/.hermes/.env`
(one-time manual step) so Hermes stops silently dropping messages before we
ever see them — see the doc above for why that's now safe.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger("vigil-image-only")

PY = "/home/user/anaconda3/envs/ai/bin/python"
ROOT = "/home/user/Documents/job_engine"
JE_ENV = Path(ROOT) / ".env"

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from app.telegram_guests import (  # noqa: E402
        DEFAULT_TTL_MINUTES,
        add_guest,
        format_ttl,
        is_allowed,
        list_guests,
        owner_ids,
        revoke_guest,
    )
    _GUESTS_OK = True
except Exception as e:  # pragma: no cover - defensive, see fallback below
    logger.exception("telegram_guests import failed, falling open: %s", e)
    _GUESTS_OK = False
    DEFAULT_TTL_MINUTES = 60.0

    def is_allowed(_user_id):  # noqa: ANN001 - fail open, never lock Ashok out
        return True

    def add_guest(*_a, **_k):
        return {}

    def revoke_guest(*_a, **_k):
        return False

    def list_guests():
        return []

    def owner_ids():
        return set()

    def format_ttl(seconds):
        return f"{max(0, int(seconds) // 60)}m"


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


def _bot_token() -> str:
    hermes_env = Path.home() / ".hermes" / ".env"
    if hermes_env.exists():
        for ln in hermes_env.read_text().splitlines():
            if ln.startswith("TELEGRAM_BOT_TOKEN="):
                return ln.split("=", 1)[1].strip()
    return ""


def _reply(chat: str, text: str) -> None:
    """Direct Telegram send — bypasses DIRECTOR entirely for guest-management
    replies so `/allow` etc. never burn an OpenAI call or wait on Ollama."""
    token = _bot_token()
    if not token or not chat:
        logger.warning("guest-reply skipped: missing token or chat=%s", chat)
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        body = urllib.parse.urlencode({
            "chat_id": chat,
            "text": text,
            "disable_web_page_preview": "true",
        }).encode()
        req = urllib.request.Request(url, data=body)
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except Exception as e:
        logger.warning("guest-reply failed chat=%s: %s", chat, e)


def _handle_guest_command(text: str, chat: str):
    """Owner-only `/allow` `/revoke` `/guests`. Returns a gateway skip dict
    when the message was a recognised admin command, else None so the
    caller falls through to the normal allow/deny + DIRECTOR path."""
    stripped = text.strip()
    lower = stripped.lower()
    is_owner = chat in owner_ids()

    if lower.startswith("/allow"):
        if not is_owner:
            return None
        parts = stripped.split(maxsplit=3)
        if len(parts) < 2:
            _reply(chat, f"Usage: /allow <telegram_id> [minutes={int(DEFAULT_TTL_MINUTES)}] [label]")
            return {"action": "skip", "reason": "allow-usage"}
        guest_id = parts[1]
        minutes = DEFAULT_TTL_MINUTES
        label_start = 2
        if len(parts) >= 3:
            try:
                minutes = float(parts[2])
                label_start = 3
            except ValueError:
                label_start = 2
        label = " ".join(parts[label_start:]) if len(parts) > label_start else ""
        entry = add_guest(guest_id, minutes=minutes, label=label, added_by=chat)
        _reply(
            chat,
            f"Allowed {guest_id} for {format_ttl(entry.get('minutes', minutes) * 60)}"
            + (f" ({label})" if label else "") + ".",
        )
        _reply(guest_id, "You're approved to chat here now — go ahead.")
        return {"action": "skip", "reason": "allow-done"}

    if lower.startswith("/revoke"):
        if not is_owner:
            return None
        parts = stripped.split(maxsplit=1)
        if len(parts) < 2:
            _reply(chat, "Usage: /revoke <telegram_id>")
            return {"action": "skip", "reason": "revoke-usage"}
        ok = revoke_guest(parts[1])
        _reply(chat, ("Revoked " if ok else "No such active guest: ") + parts[1])
        return {"action": "skip", "reason": "revoke-done"}

    if lower in ("/guests", "/guestlist"):
        if not is_owner:
            return None
        guests = list_guests()
        if not guests:
            _reply(chat, "No active guests.")
        else:
            lines = ["Active guests:"]
            for g in guests:
                left = format_ttl(g["expires_in_s"])
                label = f" — {g['label']}" if g["label"] else ""
                lines.append(f"- {g['user_id']}{label} ({left} left)")
            _reply(chat, "\n".join(lines))
        return {"action": "skip", "reason": "guests-list"}

    return None


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

    guest_reply = _handle_guest_command(text, chat)
    if guest_reply is not None:
        return guest_reply

    if not is_allowed(chat):
        # Silent drop by design (existing private-ops posture) — Ashok grants
        # access via `/allow <id>` once he has the sender's numeric Telegram
        # id (they get it from @userinfobot). See documents/kanban.md card #1.
        logger.info("DIRECTOR blocked unauthorised chat=%s text=%s", chat, text[:60])
        return {"action": "skip", "reason": "not-authorised"}

    logger.info("DIRECTOR dispatch bot=%s chat=%s text=%s", bot, chat, text[:120])
    t = threading.Thread(target=_run_director, args=(text, bot, chat), daemon=True)
    t.start()
    t.join(timeout=600)

    return {"action": "skip", "reason": "director-handled"}


def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", telegram_to_director)
    logger.info("DIRECTOR gate armed — Telegram text-first (chat /summarize /image)")
