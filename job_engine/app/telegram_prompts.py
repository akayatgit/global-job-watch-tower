"""Prompt Tower on Telegram — Ashok's daily top-10 deck (owner-only).

Everything here is deterministic formatting over the tower API: the list,
the full prompt, the ⭐ rating, the "📸 product image → ✅ make video" flow,
and the render watcher that uploads the finished MP4 + Instagram card back
into the chat. No model composes anything a human reads on this surface.

Callback data prefix: ``pt:``. Owner photo without a caption arrives as the
synthetic ``pt:photo`` tap (see scripts/telegram_job_bot.py) so the durable
text-only inbox still carries it.
"""

from __future__ import annotations

import base64
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable

from app.telegram_buttons import ButtonReply

logger = logging.getLogger(__name__)

CALLBACK_PREFIX = 'pt:'
RENDER_POLL_S = 15
RENDER_MAX_WAIT_S = 20 * 60
PERF_TOKEN_RE = re.compile(r'\b(likes|comments|saves|shares|views)\s*[=:]\s*(\d+)', re.I)
STATE_SELECTED = 'prompt_selected:{chat}'
STATE_AWAIT_IMAGE = 'prompt_await_image:{chat}'
STATE_PHOTO = 'pending_prompt_photo:{chat}'
STATE_DAILY_SENT = 'prompt_daily_sent:{day}'

PROMPTS_USAGE = (
    'Usage: /prompts [YYYY-MM-DD] — today\'s top-10 video prompts with buttons.\n'
    '/promptscan runs collection + scoring now · /addprompt <text> adds one · '
    '/promptperf <id> likes=.. comments=.. saves=.. views=.. teaches the ranker · '
    '/promptstats shows the tower.'
)


def _score(value: Any) -> str:
    try:
        return f'{float(value):.0f}'
    except (TypeError, ValueError):
        return '–'


def _source_label(prompt: dict[str, Any]) -> str:
    source = str(prompt.get('source') or 'web')
    author = prompt.get('author')
    if source == 'reddit' and author:
        return f'r/… u/{author}'
    if source == 'instagram':
        return 'Instagram'
    if source == 'manual':
        return 'yours'
    if author and source == 'web':
        return str(author)
    return source


class PromptDeck:
    """Owner-only prompt commands + ``pt:`` callbacks. Injected I/O only."""

    def __init__(
        self,
        sessions,
        *,
        api_get: Callable[[str, dict | None], Any],
        api_post: Callable[[str, dict | None], Any],
        download_photo: Callable[[str], tuple[bytes, str]] | None = None,
        fetch_asset: Callable[[str], bytes] | None = None,
        send_photo_bytes: Callable[[str, bytes, str], None] | None = None,
        send_video_bytes: Callable[[str, bytes, str], None] | None = None,
        send_text: Callable[[str, str], None] | None = None,
        on_render_started: Callable[[str, int], None] | None = None,
    ):
        self.sessions = sessions
        self.on_render_started = on_render_started
        self.api_get = api_get
        self.api_post = api_post
        self.download_photo = download_photo
        self.fetch_asset = fetch_asset
        self.send_photo_bytes = send_photo_bytes
        self.send_video_bytes = send_video_bytes
        self.send_text = send_text

    # ------------------------------------------------------------ commands

    def handle_command(self, chat_id: str, command: str, arg: str) -> str | ButtonReply:
        if command == 'prompts':
            return self.list_reply(chat_id, (arg or '').strip() or None)
        if command == 'promptscan':
            return self.scan_reply()
        if command == 'addprompt':
            return self.add_reply(chat_id, arg)
        if command == 'promptstats':
            return self.stats_reply()
        if command == 'promptperf':
            return self.performance_reply(arg)
        return PROMPTS_USAGE

    def list_reply(self, chat_id: str, day: str | None = None) -> str | ButtonReply:
        params = {'day': day} if day else None
        try:
            data = self.api_get('/api/prompts/today', params)
        except Exception:
            return 'Tower is unreachable right now — try /prompts again in a minute.'
        if not isinstance(data, dict):
            return 'Tower is unreachable right now — try /prompts again in a minute.'
        prompts = data.get('prompts') or []
        label = data.get('day') or (day or 'today')
        if not prompts:
            return ButtonReply(
                f'No shortlist for {label} yet. The daily run collects + scores at '
                '09:00 IST; tap Scan now to run it immediately.',
                [[('🔄 Scan now', 'pt:scan')]],
            )
        lines = [f'🎬 TOP {len(prompts)} VIDEO PROMPTS · {label}', 'Tap a number for the full prompt.', '']
        buttons: list[tuple[str, str]] = []
        for item in prompts:
            rank = item.get('rank') or len(buttons) + 1
            flags = ' 🔥' if item.get('is_outlier') else ''
            category = f" · {item['category']}" if item.get('category') else ''
            model = f" · {item['model_hint']}" if item.get('model_hint') else ''
            rating = f" · ⭐{item['rating']}" if item.get('rating') else ''
            lines.append(
                f"{rank}. {_score(item.get('final_score'))}/100{flags} — "
                f"{item.get('title') or 'Untitled'}{category}{model} — {_source_label(item)}{rating}"
            )
            buttons.append((str(rank), f"pt:sel:{item.get('id')}"))
        lines.append('')
        lines.append('🔥 = beats the proven-winners baseline by >1σ.')
        keyboard = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
        keyboard.append([('🔄 Scan now', 'pt:scan'), ('📊 Stats', 'pt:stats')])
        return ButtonReply('\n'.join(lines), keyboard)

    def scan_reply(self) -> str:
        try:
            result = self.api_post('/api/prompts/scan', {'force': False})
        except Exception:
            return 'Tower is unreachable right now — try /promptscan again in a minute.'
        if isinstance(result, dict) and result.get('queued'):
            return (
                '🔄 Scan queued — collecting from every source and scoring with Hermes. '
                "I'll send the top 10 here the moment it lands."
            )
        if isinstance(result, dict):
            return (
                f"Scan done · {result.get('candidates', 0)} candidates · "
                f"{result.get('created', 0)} new · {result.get('scored', 0)} scored · "
                f"{result.get('shortlisted', 0)} shortlisted. Send /prompts."
            )
        return 'Scan request failed — check /health.'

    def add_reply(self, chat_id: str, arg: str) -> str | ButtonReply:
        text = (arg or '').strip()
        if len(text) < 60:
            return (
                'Usage: /addprompt <full prompt text> — paste the whole prompt '
                '(180+ characters with camera/lighting + product/motion detail).'
            )
        try:
            result = self.api_post('/api/prompts/ingest', {'text': text, 'author': 'ashok'})
        except Exception as exc:
            if '422' in str(exc):
                return (
                    "That text doesn't read as a video prompt yet — it needs camera or "
                    'lighting detail plus a product or motion, 180+ characters.'
                )
            return 'Tower is unreachable right now — try /addprompt again in a minute.'
        prompt = (result or {}).get('prompt') or {}
        outcome = (result or {}).get('outcome')
        if outcome in ('duplicate', 'near_duplicate'):
            return f"Already in the tower as #{prompt.get('id')} (score {_score(prompt.get('final_score'))})."
        return ButtonReply(
            f"✅ Added #{prompt.get('id')} · score {_score(prompt.get('final_score'))}/100 "
            f"(detail {_score(prompt.get('ai_detail'))} · flow {_score(prompt.get('ai_flow'))})"
            f"{' · 🔥 outlier' if prompt.get('is_outlier') else ''}.",
            [[('Open', f"pt:sel:{prompt.get('id')}")]],
        )

    def stats_reply(self) -> str:
        try:
            data = self.api_get('/api/prompts/stats', None)
        except Exception:
            return 'Tower is unreachable right now — try /promptstats again in a minute.'
        if not isinstance(data, dict):
            return 'Tower is unreachable right now — try /promptstats again in a minute.'
        sources = ' · '.join(f'{k} {v}' for k, v in sorted((data.get('by_source') or {}).items())) or 'none yet'
        baseline = (
            f"{_score(data.get('baseline_mean'))} ± {_score(data.get('baseline_std'))}"
            if data.get('baseline_mean') is not None else 'not yet (rate or post prompts to build it)'
        )
        last = data.get('last_collected_at')
        return '\n'.join([
            '📊 PROMPT TOWER',
            f"Prompts {data.get('total', 0)} · scored {data.get('scored', 0)} · pending {data.get('pending_score', 0)}",
            f"Shortlisted today {data.get('shortlisted_today', 0)} · posted {data.get('posted', 0)} · videos {data.get('renders_done', 0)}",
            f"Winners in RAG {data.get('exemplars', 0)} · outliers {data.get('outliers', 0)}",
            f'Baseline (winners) {baseline}',
            f'Sources: {sources}',
            f"Last catch: {_ago(last)}",
        ])

    def performance_reply(self, arg: str) -> str:
        text = (arg or '').strip()
        match = re.match(r'^#?(\d+)\b', text)
        metrics = {k.lower(): int(v) for k, v in PERF_TOKEN_RE.findall(text)}
        if not match or not metrics:
            return 'Usage: /promptperf <id> likes=120 comments=8 saves=30 shares=4 views=5400'
        prompt_id = int(match.group(1))
        try:
            result = self.api_post(f'/api/prompts/{prompt_id}/performance', metrics)
        except Exception as exc:
            if '404' in str(exc):
                return f'No prompt #{prompt_id}.'
            return 'Tower is unreachable right now — try again in a minute.'
        return (
            f"📈 #{prompt_id} performance saved — score {_score((result or {}).get('performance_score'))}"
            f"{' · now a RAG winner' if (result or {}).get('exemplar') else ''}. "
            'Tomorrow\'s scoring calibrates on it.'
        )

    # ----------------------------------------------------------- callbacks

    def handle_callback(self, chat_id: str, payload: str) -> ButtonReply:
        body = payload[len(CALLBACK_PREFIX):] if payload.startswith(CALLBACK_PREFIX) else payload
        parts = body.split(':')
        action = parts[0]
        if action == 'list':
            return _as_reply(self.list_reply(chat_id))
        if action == 'scan':
            return ButtonReply(self.scan_reply())
        if action == 'stats':
            return ButtonReply(self.stats_reply())
        if action == 'sel' and len(parts) >= 2 and parts[1].isdigit():
            return self.detail_reply(chat_id, int(parts[1]))
        if action == 'img' and len(parts) >= 2 and parts[1].isdigit():
            prompt_id = int(parts[1])
            self.sessions.set_state(STATE_AWAIT_IMAGE.format(chat=chat_id), prompt_id)
            self.sessions.set_state(STATE_SELECTED.format(chat=chat_id), prompt_id)
            return ButtonReply(
                f'📸 Send the product photo now (as a photo, no caption needed). '
                f"I'll pair it with prompt #{prompt_id} and ask you to confirm before rendering.",
                [[('✖ Cancel', 'pt:cancel')]],
            )
        if action == 'photo':
            return self.photo_reply(chat_id)
        if action == 'go' and len(parts) >= 2 and parts[1].isdigit():
            return self.render_reply(chat_id, int(parts[1]))
        if action == 'cancel':
            self._clear_pending(chat_id)
            return ButtonReply('Cancelled — nothing rendered.', [[('◂ Top 10', 'pt:list')]])
        if action == 'rate' and len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
            return self.rate_reply(int(parts[1]), int(parts[2]))
        if action == 'posted' and len(parts) >= 2 and parts[1].isdigit():
            return self.posted_reply(int(parts[1]))
        return ButtonReply(PROMPTS_USAGE)

    def detail_reply(self, chat_id: str, prompt_id: int) -> ButtonReply:
        try:
            prompt = self.api_get(f'/api/prompts/{prompt_id}', None)
        except Exception as exc:
            if '404' in str(exc):
                return ButtonReply(f'No prompt #{prompt_id}.', [[('◂ Top 10', 'pt:list')]])
            return ButtonReply('Tower is unreachable right now — try again in a minute.')
        if not isinstance(prompt, dict):
            return ButtonReply('Tower is unreachable right now — try again in a minute.')
        self.sessions.set_state(STATE_SELECTED.format(chat=chat_id), prompt_id)
        header = [
            f"🎬 PROMPT #{prompt_id} · {_score(prompt.get('final_score'))}/100"
            f"{' 🔥 outlier' if prompt.get('is_outlier') else ''}",
            f"Detail {_score(prompt.get('ai_detail'))} · Flow {_score(prompt.get('ai_flow'))} · "
            f"Structure {_score(prompt.get('heuristic_score'))}"
            + (f" · baseline {_score(prompt.get('baseline_mean'))}" if prompt.get('baseline_mean') is not None else ''),
        ]
        meta = [
            bit for bit in (
                prompt.get('category'),
                prompt.get('model_hint'),
                _source_label(prompt),
                f"⭐{prompt['rating']}" if prompt.get('rating') else None,
                prompt.get('status') if prompt.get('status') not in (None, 'new', 'shortlisted') else None,
            ) if bit
        ]
        if meta:
            header.append(' · '.join(str(m) for m in meta))
        reasons = [r for r in (prompt.get('ai_reasons') or []) if r]
        if reasons:
            header.append('Hermes: ' + ' / '.join(reasons[:3]))
        if prompt.get('source_url'):
            header.append(f"Source: {prompt['source_url']}")
        body = '\n'.join(header) + '\n\n' + str(prompt.get('text') or '')
        keyboard = [
            [('📸 Send product image → video', f'pt:img:{prompt_id}')],
            [(f'⭐{n}', f'pt:rate:{prompt_id}:{n}') for n in range(1, 6)],
            [('📣 Posted on Instagram', f'pt:posted:{prompt_id}'), ('◂ Top 10', 'pt:list')],
        ]
        return ButtonReply(body, keyboard)

    def photo_reply(self, chat_id: str) -> ButtonReply:
        raw = self.sessions.get_state(STATE_AWAIT_IMAGE.format(chat=chat_id), '')
        file_id = self.sessions.get_state(STATE_PHOTO.format(chat=chat_id), '')
        if not raw.isdigit():
            return ButtonReply(
                'Got the photo. Pick a prompt first: /prompts → tap a number → 📸, '
                "then send the photo again and I'll pair them.",
                [[('◂ Top 10', 'pt:list')]],
            )
        if not file_id:
            return ButtonReply('I could not read that photo — send it again as a photo (not a file).')
        prompt_id = int(raw)
        return ButtonReply(
            f'Prompt #{prompt_id} + your product photo are paired.\n'
            'Make the video now? The prompt is used verbatim; your photo is the first frame.',
            [[('✅ Make video', f'pt:go:{prompt_id}'), ('✖ Cancel', 'pt:cancel')]],
        )

    def render_reply(self, chat_id: str, prompt_id: int) -> ButtonReply:
        file_id = self.sessions.get_state(STATE_PHOTO.format(chat=chat_id), '')
        if not file_id or self.download_photo is None:
            return ButtonReply(
                'No product photo on hand — tap 📸 on the prompt and send the photo first.',
                [[('◂ Top 10', 'pt:list')]],
            )
        try:
            data, content_type = self.download_photo(file_id)
        except Exception:
            logger.exception('telegram photo download failed')
            return ButtonReply('Could not download the photo from Telegram — send it again.')
        payload = {
            'image_base64': base64.b64encode(data).decode('ascii'),
            'chat_id': str(chat_id),
            'content_type': content_type or 'image/jpeg',
        }
        try:
            render = self.api_post(f'/api/prompts/{prompt_id}/render', payload)
        except Exception as exc:
            if '404' in str(exc):
                return ButtonReply(f'No prompt #{prompt_id}.')
            logger.exception('render request failed')
            return ButtonReply('Tower could not start the render — check /health and try again.')
        self._clear_pending(chat_id)
        if not isinstance(render, dict) or not render.get('id'):
            return ButtonReply('Tower could not start the render — check /health and try again.')
        if render.get('status') == 'failed':
            return ButtonReply(f"Render failed to queue: {render.get('error') or 'unknown error'}")
        if self.on_render_started is not None:
            try:
                self.on_render_started(str(chat_id), int(render['id']))
            except Exception:
                logger.exception('render watcher failed to start render=%s', render.get('id'))
        return ButtonReply(
            f"🎬 Rendering prompt #{prompt_id} (render {render['id']}). Instagram card is ready; "
            "the AI video usually takes 2–6 minutes — I'll send both here.",
            [[('◂ Top 10', 'pt:list')]],
            )

    def rate_reply(self, prompt_id: int, rating: int) -> ButtonReply:
        try:
            result = self.api_post(f'/api/prompts/{prompt_id}/rate', {'rating': rating})
        except Exception as exc:
            if '404' in str(exc):
                return ButtonReply(f'No prompt #{prompt_id}.')
            return ButtonReply('Tower is unreachable right now — try again in a minute.')
        winner = ' · now a RAG winner' if (result or {}).get('exemplar') else ''
        return ButtonReply(
            f'⭐{rating} saved for #{prompt_id}{winner}. Tomorrow\'s scoring calibrates on it.',
            [[('◂ Top 10', 'pt:list'), ('Open', f'pt:sel:{prompt_id}')]],
        )

    def posted_reply(self, prompt_id: int) -> ButtonReply:
        try:
            self.api_post(f'/api/prompts/{prompt_id}/posted', {})
        except Exception as exc:
            if '404' in str(exc):
                return ButtonReply(f'No prompt #{prompt_id}.')
            return ButtonReply('Tower is unreachable right now — try again in a minute.')
        return ButtonReply(
            f'📣 #{prompt_id} marked posted. When numbers come in: '
            f'/promptperf {prompt_id} likes=.. comments=.. saves=.. views=..',
            [[('◂ Top 10', 'pt:list')]],
        )

    # ----------------------------------------------------- render watcher

    def watch_render(
        self,
        chat_id: str,
        render_id: int,
        *,
        poll_s: float = RENDER_POLL_S,
        max_wait_s: float = RENDER_MAX_WAIT_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> str:
        """Block until the render finishes (or times out), then deliver the
        card + video into the chat. Returns the terminal status."""
        waited = 0.0
        card_sent = False
        while True:
            try:
                render = self.api_get(f'/api/prompts/renders/{render_id}', None)
            except Exception:
                render = None
            if isinstance(render, dict):
                if not card_sent and render.get('card_image_key') and self.fetch_asset and self.send_photo_bytes:
                    try:
                        self.send_photo_bytes(
                            chat_id,
                            self.fetch_asset(render['card_image_key']),
                            f"📇 Instagram card for prompt #{render.get('prompt_id')} — post-ready.",
                        )
                        card_sent = True
                    except Exception:
                        logger.exception('card delivery failed render=%s', render_id)
                        card_sent = True
                status = str(render.get('status') or '')
                if status == 'done':
                    self._deliver_video(chat_id, render)
                    return 'done'
                if status == 'failed':
                    if self.send_text:
                        self.send_text(
                            chat_id,
                            f"❌ Video render {render_id} failed: {render.get('error') or 'unknown error'}. "
                            'Tap 📸 on the prompt to try again.',
                        )
                    return 'failed'
            if waited >= max_wait_s:
                if self.send_text:
                    self.send_text(
                        chat_id,
                        f'⏳ Render {render_id} is still running after {int(max_wait_s // 60)} min — '
                        'I will stop watching; /promptstats shows finished videos.',
                    )
                return 'timeout'
            sleep(poll_s)
            waited += poll_s

    def _deliver_video(self, chat_id: str, render: dict[str, Any]) -> None:
        caption = (
            f"🎬 Prompt #{render.get('prompt_id')} — video ready"
            f"{' · ' + str(render['model']) if render.get('model') else ''}\n{render.get('video_url') or ''}"
        ).strip()
        key = render.get('video_key')
        if key and self.fetch_asset and self.send_video_bytes:
            try:
                self.send_video_bytes(chat_id, self.fetch_asset(key), caption)
                return
            except Exception:
                logger.exception('video upload failed render=%s', render.get('id'))
        if self.send_text:
            self.send_text(chat_id, caption)

    # ------------------------------------------------------- daily push

    def daily_push_due(self, day: str | None = None) -> bool:
        day = day or datetime.now(timezone.utc).date().isoformat()
        return self.sessions.get_state(STATE_DAILY_SENT.format(day=day), '') != '1'

    def deliver_daily(self, owner_chat_ids: set[str], send_keyboard: Callable[[str, str, list | None], None]) -> bool:
        """Send today's top-10 to every owner chat once the shortlist exists.
        Returns True when delivered (and remembered for the day)."""
        day = datetime.now(timezone.utc).date().isoformat()
        if not self.daily_push_due(day):
            return False
        reply = self.list_reply(next(iter(owner_chat_ids), ''), day)
        if not isinstance(reply, ButtonReply) or not (reply.keyboard and len(reply.keyboard) > 1):
            return False  # no shortlist yet — the "Scan now" nudge is not the daily deck
        for chat_id in owner_chat_ids:
            send_keyboard(chat_id, reply.text, reply.keyboard)
        self.sessions.set_state(STATE_DAILY_SENT.format(day=day), '1')
        return True

    # --------------------------------------------------------------- misc

    def _clear_pending(self, chat_id: str) -> None:
        self.sessions.set_state(STATE_AWAIT_IMAGE.format(chat=chat_id), '')
        self.sessions.set_state(STATE_PHOTO.format(chat=chat_id), '')


def _as_reply(value: str | ButtonReply) -> ButtonReply:
    return value if isinstance(value, ButtonReply) else ButtonReply(value)


def _ago(iso: str | None) -> str:
    if not iso:
        return 'never'
    try:
        stamp = datetime.fromisoformat(str(iso))
    except ValueError:
        return 'never'
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    seconds = max(0, int((datetime.now(timezone.utc) - stamp).total_seconds()))
    if seconds < 90:
        return 'just now'
    minutes = seconds // 60
    if minutes < 60:
        return f'{minutes}m ago'
    hours = minutes // 60
    if hours < 48:
        return f'{hours}h ago'
    return f'{hours // 24}d ago'
