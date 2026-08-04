"""COURIER gate: forward Telegram text to DIRECTOR (OpenAI), skip Hermes Ollama chat.

Also enforces our own Telegram guest allowlist (documents/kanban.md card #1,
documents/hermes-agent-integration.md) so Ashok can grant/revoke access from
his phone via `/allow` `/revoke` `/allowuser` `/revokeuser` `/guests` without
any ThinkPad terminal access. This requires `TELEGRAM_ALLOW_ALL_USERS=true`
in `~/.hermes/.env` (one-time manual step) so Hermes stops silently dropping
messages before we ever see them — see the doc above for why that's now safe.

Allowlisting works two ways: by numeric Telegram id (`/allow`, needs a
detour through @userinfobot) or directly by `@username` (`/allowuser`, or a
permanent code-tracked default in `app.telegram_guests.DEFAULT_ALLOWED_USERNAMES`
— no id lookup needed). See `_sender_username()` for the username lookup.
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
        add_username,
        format_ttl,
        is_allowed,
        list_guests,
        list_usernames,
        owner_ids,
        revoke_guest,
        revoke_username,
    )
    _GUESTS_OK = True
except Exception as e:  # pragma: no cover - defensive, see fallback below
    logger.exception("telegram_guests import failed, falling open: %s", e)
    _GUESTS_OK = False
    DEFAULT_TTL_MINUTES = 60.0

    def is_allowed(_user_id, username=None):  # noqa: ANN001 - fail open, never lock Ashok out
        return True

    def add_guest(*_a, **_k):
        return {}

    def revoke_guest(*_a, **_k):
        return False

    def list_guests():
        return []

    def add_username(*_a, **_k):
        return {}

    def revoke_username(*_a, **_k):
        return False

    def list_usernames():
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


def _sender_username(event) -> str:
    """Best-effort Telegram @username of the message sender.

    We don't control the Hermes connector's event shape, so this checks every
    attribute name we've plausibly seen used for it, then falls back to the
    raw Telegram update dict if the connector exposes one. Returns "" (never
    raises) when nothing is found — callers must treat that as "unknown", not
    "no username set", since numeric chat_id remains the source of truth.
    """
    src = getattr(event, "source", None)
    for holder in (src, event):
        if holder is None:
            continue
        for attr in ("username", "user_username", "from_username", "sender_username", "handle"):
            val = getattr(holder, attr, None)
            if val:
                return str(val).lstrip("@")
        user_obj = getattr(holder, "user", None) or getattr(holder, "from_user", None)
        if user_obj is not None:
            val = getattr(user_obj, "username", None)
            if val:
                return str(val).lstrip("@")
    for holder in (src, event):
        raw = getattr(holder, "raw", None) if holder is not None else None
        if isinstance(raw, dict):
            frm = (raw.get("message") or raw).get("from") if isinstance(raw.get("message") or raw, dict) else None
            if isinstance(frm, dict) and frm.get("username"):
                return str(frm["username"]).lstrip("@")
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
    """Owner-only `/allow` `/revoke` `/allowuser` `/revokeuser` `/guests`.
    Returns a gateway skip dict when the message was a recognised admin
    command, else None so the caller falls through to the normal allow/deny
    + DIRECTOR path."""
    stripped = text.strip()
    lower = stripped.lower()
    is_owner = chat in owner_ids()

    # Check the "user" variants before the plain /allow /revoke prefixes
    # below, since "/allowuser" and "/revokeuser" both start with those.
    if lower.startswith("/allowuser"):
        if not is_owner:
            return None
        parts = stripped.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            _reply(chat, "Usage: /allowuser <telegram_username> (with or without @)")
            return {"action": "skip", "reason": "allowuser-usage"}
        handle = parts[1].strip().lstrip("@")
        add_username(handle, added_by=chat)
        _reply(chat, f"Allowed @{handle} — their next message gets a real reply.")
        return {"action": "skip", "reason": "allowuser-done"}

    if lower.startswith("/revokeuser"):
        if not is_owner:
            return None
        parts = stripped.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            _reply(chat, "Usage: /revokeuser <telegram_username>")
            return {"action": "skip", "reason": "revokeuser-usage"}
        handle = parts[1].strip().lstrip("@")
        ok = revoke_username(handle)
        if ok:
            _reply(chat, f"Revoked @{handle}")
        else:
            _reply(chat, f"@{handle} is either a permanent default (code change needed) or wasn't granted.")
        return {"action": "skip", "reason": "revokeuser-done"}

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
        usernames = list_usernames()
        lines = []
        if usernames:
            lines.append("Allowed usernames:")
            for u in usernames:
                tag = "default" if u["source"] == "default" else "granted"
                lines.append(f"- @{u['username']} ({tag})")
        if guests:
            if lines:
                lines.append("")
            lines.append("Active guests (by id):")
            for g in guests:
                left = format_ttl(g["expires_in_s"])
                label = f" — {g['label']}" if g["label"] else ""
                lines.append(f"- {g['user_id']}{label} ({left} left)")
        if not lines:
            lines = ["No active guests."]
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


def _run_director(text: str, bot: str, chat: str, persona: str = "owner") -> None:
    try:
        cmd = [
            PY, "-m", "app.director.router",
            "--bot", bot,
            "--chat", chat,
            "--text", text,
            "--persona", persona,
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


def _telegram_to_director_inner(event, gateway=None, session_store=None, **kwargs):
    if not _is_telegram(event):
        return None

    text = (getattr(event, "text", None) or "").strip()
    if not text:
        return {"action": "skip", "reason": "telegram-empty"}

    bot = _bot_username(event)
    chat = _chat_id(event)
    sender = _sender_username(event)

    guest_reply = _handle_guest_command(text, chat)
    if guest_reply is not None:
        return guest_reply

    if not is_allowed(chat, username=sender):
        # Silent drop by design (existing private-ops posture) — Ashok grants
        # access via `/allow <id>` (needs @userinfobot) or `/allowuser
        # <handle>` (no id lookup needed) once he knows who's asking. See
        # documents/kanban.md card #1.
        logger.info(
            "DIRECTOR blocked unauthorised chat=%s username=%s text=%s",
            chat, sender or "(unknown)", text[:60],
        )
        return {"action": "skip", "reason": "not-authorised"}

    is_owner = chat in owner_ids()
    persona = "owner" if is_owner else "guest"
    logger.info(
        "DIRECTOR dispatch bot=%s chat=%s persona=%s text=%s",
        bot, chat, persona, text[:120],
    )
    t = threading.Thread(
        target=_run_director, args=(text, bot, chat, persona), daemon=True,
    )
    t.start()
    if is_owner:
        # Existing owner behavior: block until DIRECTOR finishes
        t.join(timeout=600)
    # Guests: return skip IMMEDIATELY so the Hermes built-in agent can never
    # win a race and answer with engine-room talk (incident 2026-08-04:
    # guest "hi" got a Hermes skills/platform essay). DIRECTOR replies
    # asynchronously to the guest's chat via DIRECTOR_TARGET_CHAT.
    return {"action": "skip", "reason": f"director-handled-{persona}"}


def telegram_to_director(event, gateway=None, session_store=None, **kwargs):
    """Hard outer guard (2026-08-04 incident): Hermes' documented hook contract
    says an UNCAUGHT exception here makes the gateway "fall through to normal
    dispatch" — i.e. its own built-in agent answers instead, with none of our
    gating, blackbox rules, or link requirements. Real log evidence from that
    exact night: `gateway.platforms.base: Sending response (2580 chars) to
    <guest chat>` — Hermes' own send path, not ours — right where a guest
    should have gotten a plain skip. Never again: whatever happens inside,
    this outer function ALWAYS returns a recognized action dict, never raises."""
    try:
        result = _telegram_to_director_inner(event, gateway, session_store, **kwargs)
        return result if result is not None else {"action": "skip", "reason": "no-match"}
    except Exception as e:
        logger.exception("telegram_to_director crashed — forcing skip: %s", e)
        try:
            chat = _chat_id(event)
            if chat:
                _reply(
                    chat,
                    "Had a hiccup on my end — send that again in a moment.",
                )
        except Exception:
            pass
        return {"action": "skip", "reason": "plugin-error"}


def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", telegram_to_director)
    logger.info("DIRECTOR gate armed — Telegram text-first (chat /summarize /image)")
