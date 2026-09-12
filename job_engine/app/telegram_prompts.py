"""Prompt Tower on Telegram — daily top-10 plus public reverse prompt.

Every user can run /igtovid · /pintovid. No jobseeker copy.

Everything here is deterministic formatting over the tower API: the list,
the full prompt, the ⭐ rating, the "📸 product image → ✅ make video" flow,
the render watcher that uploads the finished MP4 + Instagram card back
into the chat, and reverse prompt (`/igtovid` · `/pintovid`) which delivers
the Gemini-authored timestamped prompt verbatim. Reverse prompt is the
one place a model authors a generation prompt.

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
REF_SEND_GAP_S = 0.45
REF_SEND_TRIES = 4
RETRY_AFTER_RE = re.compile(r'retry after (\d+)', re.I)
PERF_TOKEN_RE = re.compile(r'\b(likes|comments|saves|shares|views)\s*[=:]\s*(\d+)', re.I)
STATE_SELECTED = 'prompt_selected:{chat}'
STATE_AWAIT_IMAGE = 'prompt_await_image:{chat}'
STATE_PHOTO = 'pending_prompt_photo:{chat}'
STATE_DAILY_SENT = 'prompt_daily_sent:{day}'
# Reverse prompt (2026-09-10): /igtovid · /pintovid → waiting for the URL
# (or the video file itself) → tower row polled by watch_reverse.
STATE_AWAIT_URL = 'prompt_await_url:{chat}'
STATE_AWAIT_TITLE = 'prompt_await_title:{chat}'
STATE_AWAIT_TWIST = 'prompt_await_twist:{chat}'
STATE_AWAIT_TWIST_APPLY = 'prompt_await_twist_apply:{chat}'
STATE_AWAIT_MODEL = 'prompt_await_reverse_model:{chat}'
STATE_PENDING_URL = 'prompt_pending_reverse_url:{chat}'
STATE_PENDING_TITLE = 'prompt_pending_reverse_title:{chat}'
STATE_PENDING_TWIST = 'prompt_pending_reverse_twist:{chat}'
STATE_VIDEO = 'pending_prompt_video:{chat}'
STATE_LAST_REVERSE = 'prompt_last_reverse:{chat}'
STATE_REVERSE_DELIVERED = 'prompt_reverse_delivered:{rid}'
STATE_TWIST_STILLS_DELIVERED = 'prompt_twist_stills_delivered:{rid}'
STATE_TWIST_DELIVERED = 'prompt_twist_delivered:{rid}'
STATE_REVERSE_ANNOUNCED = 'prompt_reverse_announced:{rid}'
STATE_TWIST_ANNOUNCED = 'prompt_twist_announced:{rid}'
REVERSE_COMMANDS = frozenset({'igtovid', 'pintovid', 'pintovideo', 'reverseprompt'})
FRAME_PAGE = 4
REVERSE_POLL_S = 15
REVERSE_MAX_WAIT_S = 25 * 60
TWIST_MAX_WAIT_S = 30 * 60
DESCRIBE_HEARTBEAT_S = 90
TELEGRAM_TEXT_LIMIT = 3900
# Ashok (2026-09-11): /igtovid must answer at once, one line, no essay.
# Canary copy (Ashok 2026-09-12): if Telegram still shows the old line,
# ThinkPad has not picked up main — deploy is the bug, not the bot logic.
REVERSE_ASK = 'Now Paste the link.'
REVERSE_USAGE = REVERSE_ASK
# Ashok (2026-09-11): one line each. No footer essay, no magic-pencil speech.
TITLE_ASK = 'Whats the hook?'
# Ashok (2026-09-12): twist lives on the finished clip.
# Ready message is one word — no timing essay, no Save clip/reel (2026-09-12).
READY_CAPTION = 'Ready…'
TWIST_ASK = 'Shall we twist the video?'
START_TWIST = '▶ Start the Twist'
MODEL_ASK = 'Select a Prompt Model…'
REVERSE_QUEUED = 'processing..'
REVERSE_STARTED = 'Workflow Started…'
MODEL_BUTTONS = [
    [('Gemini', 'pt:revmodel:gemini')],
    [('GPT-6 Astra', 'pt:revmodel:astra')],
    [('Claude Fable 5', 'pt:revmodel:fable')],
]

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


def _reel_engine_line(engine: Any) -> str:
    """One phone-readable phrase for the reel engine the tower found."""
    if not isinstance(engine, dict):
        return 'engine unknown'
    kind = str(engine.get('engine') or 'none')
    if kind == 'ffmpeg':
        return f"engine ffmpeg ({engine.get('video_codec') or '?'}{'' if engine.get('audio') else ', no audio'}) at {engine.get('ffmpeg')}"
    if kind == 'pyav':
        return f"engine PyAV {(engine.get('libs') or {}).get('av') or ''} (libx264 + audio)".replace('  ', ' ')
    if kind == 'opencv':
        return f"engine OpenCV {(engine.get('libs') or {}).get('cv2') or ''} (MPEG-4, silent)".replace('  ', ' ')
    searched = len(engine.get('searched') or [])
    return f'⚠️ no video engine — {searched} ffmpeg spot(s) checked, av/cv2 absent · fix: sudo apt install -y ffmpeg'


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


def save_url(url: str | None) -> str:
    from app.prompts.video_creator import as_download_url

    return as_download_url(url)


def save_keyboard(*pairs: tuple[str, str | None]) -> list[list[tuple[str, str]]]:
    """⬇️ Save clip / reel — Telegram URL buttons, not callbacks."""
    rows: list[list[tuple[str, str]]] = []
    for label, url in pairs:
        href = save_url(url)
        if href:
            rows.append([(label, href)])
    return rows


class PromptDeck:
    """Prompt commands + ``pt:`` callbacks for every user. Injected I/O only."""

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
        send_document_bytes: Callable[..., None] | None = None,
        send_text: Callable[[str, str], None] | None = None,
        on_render_started: Callable[[str, int], None] | None = None,
        on_reverse_started: Callable[[str, int], None] | None = None,
        on_twist_started: Callable[[str, int], None] | None = None,
        on_reverse_upload: Callable[..., None] | None = None,
        send_keyboard: Callable[[str, str, list], None] | None = None,
    ):
        self.sessions = sessions
        self.on_render_started = on_render_started
        self.on_reverse_started = on_reverse_started
        self.on_twist_started = on_twist_started
        self.on_reverse_upload = on_reverse_upload
        self.send_keyboard = send_keyboard
        self.api_get = api_get
        self.api_post = api_post
        self.download_photo = download_photo
        self.fetch_asset = fetch_asset
        self.send_photo_bytes = send_photo_bytes
        self.send_video_bytes = send_video_bytes
        self.send_document_bytes = send_document_bytes
        self.send_text = send_text


    def _kick_watcher(self, callback, chat_id: str, reverse_id: int) -> bool:
        """Start a reverse/twist watcher. False = already running (do not re-announce)."""
        if callback is None:
            return True
        try:
            started = callback(str(chat_id), int(reverse_id))
        except Exception:
            logger.exception('watcher kick failed id=%s', reverse_id)
            return True
        return started is not False

    def _claim_once(self, key: str) -> bool:
        """First caller wins; later watchers stay silent."""
        if self.sessions.get_state(key, '') == '1':
            return False
        self.sessions.set_state(key, '1')
        return True

    def _clear_delivery(self, reverse_id: int) -> None:
        rid = int(reverse_id)
        self.sessions.set_state(STATE_REVERSE_DELIVERED.format(rid=rid), '')
        self.sessions.set_state(STATE_TWIST_STILLS_DELIVERED.format(rid=rid), '')
        self.sessions.set_state(STATE_TWIST_DELIVERED.format(rid=rid), '')
        self.sessions.set_state(STATE_REVERSE_ANNOUNCED.format(rid=rid), '')
        self.sessions.set_state(STATE_TWIST_ANNOUNCED.format(rid=rid), '')

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
        if command in REVERSE_COMMANDS:
            return self.reverse_reply(chat_id, arg)
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
        if isinstance(result, dict) and result.get('held'):
            mins = max(1, int((result.get('resume_in_s') or 0) + 59) // 60)
            return (
                f'⏸ Scan paused — reverse prompt has the lane for about {mins} min. '
                'It will resume after that.'
            )
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
            f"Reels {data.get('reels_done', 0)} · failed {data.get('reels_failed', 0)} · {_reel_engine_line(data.get('reel_engine'))}",
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
        if payload == f'{CALLBACK_PREFIX}video':
            return self.video_reply(chat_id)
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
            )
        if action == 'photo':
            return self.photo_reply(chat_id)
        if action == 'go' and len(parts) >= 2 and parts[1].isdigit():
            return self.render_reply(chat_id, int(parts[1]))
        if action == 'cancel':
            # Old Cancel taps still clear state — we no longer show the button.
            reverse_pending = self._reverse_pending(chat_id)
            self._clear_pending(chat_id)
            if reverse_pending:
                return ButtonReply(REVERSE_ASK)
            return ButtonReply('All good — nothing rendered.', [[('◂ Top 10', 'pt:list')]])
        if action == 'rate' and len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
            return self.rate_reply(int(parts[1]), int(parts[2]))
        if action == 'posted' and len(parts) >= 2 and parts[1].isdigit():
            return self.posted_reply(int(parts[1]))
        if action == 'revmodel' and len(parts) >= 2:
            return self.maybe_take_vision_model(chat_id, parts[1])
        if action == 'twistskip':
            return self._ignore_intake_twist(chat_id)
        if action in {'imgs', 'timgs'} and len(parts) >= 2 and parts[1].isdigit():
            offset = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 0
            return self.images_reply(
                chat_id, int(parts[1]),
                kind='twist' if action == 'timgs' else 'cut',
                offset=offset,
            )
        if action in {'show', 'copy'} and len(parts) >= 2 and parts[1].isdigit():
            return self._prompt_text_reply(chat_id, int(parts[1]), copy=action == 'copy')
        if action == 'twist' and len(parts) >= 2 and parts[1].isdigit():
            return self.twist_reply(chat_id, int(parts[1]))
        if action == 'omni' and len(parts) >= 2 and parts[1].isdigit():
            return self.omni_reply(chat_id, int(parts[1]))
        if action == 'revretry' and len(parts) >= 2 and parts[1].isdigit():
            return self.retry_reverse_reply(chat_id, int(parts[1]))
        if action in {'playclip', 'playreel', 'playtwist'} and len(parts) >= 2 and parts[1].isdigit():
            return self.play_video_reply(chat_id, int(parts[1]), kind=action)
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
            [[('✅ Make video', f'pt:go:{prompt_id}')]],
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
            f"🎬 Rendering prompt #{prompt_id} (render {render['id']}). Preview card is ready; "
            "the AI clip usually takes 2–6 minutes, then I cut the post-ready reel "
            "(clip in the card + storyboard + scrolling prompt) — both land here.",
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

    # ------------------------------------------------- reverse prompt

    def reverse_reply(self, chat_id: str, arg: str) -> ButtonReply:
        """/igtovid · /pintovid [url] — start now when the URL is in the
        command, otherwise wait for the next message to carry it."""
        from app.prompts.reverse_prompt import find_url
        from app.prompts.scan_hold import break_prompt_scan

        break_prompt_scan()
        url = find_url(arg or '')
        if url:
            return self._ask_title(chat_id, source_url=url)
        self.sessions.set_state(STATE_AWAIT_URL.format(chat=chat_id), '1')
        return ButtonReply(REVERSE_ASK)

    def maybe_take_url(self, chat_id: str, text: str) -> ButtonReply | None:
        """Any user text carrying an Instagram / Pinterest link: after /igtovid
        any fetchable link counts; without the command only reel / pin
        links start a run (a stray direct .mp4 link in chat does not)."""
        from app.prompts.reverse_prompt import detect_platform, find_url

        url = find_url(text or '')
        if not url:
            return None
        awaiting = self.sessions.get_state(STATE_AWAIT_URL.format(chat=chat_id), '') == '1'
        platform = detect_platform(url)
        if platform is None or (not awaiting and platform == 'direct'):
            return None
        return self._ask_title(chat_id, source_url=url)

    def maybe_take_title(self, chat_id: str, text: str) -> ButtonReply | None:
        """Owner typed the cinematic header after the URL / forwarded clip."""
        from app.prompts.reverse_prompt import find_url

        if self.sessions.get_state(STATE_AWAIT_TITLE.format(chat=chat_id), '') != '1':
            return None
        title = ' '.join((text or '').split())
        if not title or find_url(title):
            return None
        self.sessions.set_state(STATE_AWAIT_TITLE.format(chat=chat_id), '')
        self.sessions.set_state(STATE_PENDING_TITLE.format(chat=chat_id), title[:120])
        return self._ask_vision_model(chat_id)

    def maybe_take_twist(self, chat_id: str, text: str) -> ButtonReply | None:
        """Typed magic-pencil line — only after Twist on a finished reverse.
        Leftover intake twist state must not steal a hook or start a hollow run."""
        from app.prompts.reverse_prompt import find_url
        from app.prompts.reverse_twist import clean_twist

        idea = clean_twist(text)
        if not idea or find_url(idea):
            return None
        apply_id = self.sessions.get_state(STATE_AWAIT_TWIST_APPLY.format(chat=chat_id), '')
        if apply_id.isdigit():
            self.sessions.set_state(STATE_AWAIT_TWIST_APPLY.format(chat=chat_id), '')
            return self._start_twist(chat_id, int(apply_id), idea)
        if self.sessions.get_state(STATE_AWAIT_TWIST.format(chat=chat_id), '') == '1':
            self.sessions.set_state(STATE_AWAIT_TWIST.format(chat=chat_id), '')
            self.sessions.set_state(STATE_PENDING_TWIST.format(chat=chat_id), '')
            return None
        return None

    def _ignore_intake_twist(self, chat_id: str) -> ButtonReply:
        """Old Skip button from intake twist — never start without a clip."""
        self.sessions.set_state(STATE_AWAIT_TWIST.format(chat=chat_id), '')
        self.sessions.set_state(STATE_PENDING_TWIST.format(chat=chat_id), '')
        url = self.sessions.get_state(STATE_PENDING_URL.format(chat=chat_id), '')
        has_video = bool(self.sessions.get_state(STATE_VIDEO.format(chat=chat_id), ''))
        if url or has_video:
            return self._ask_vision_model(chat_id)
        self.sessions.set_state(STATE_AWAIT_URL.format(chat=chat_id), '1')
        return ButtonReply(REVERSE_ASK)

    def twist_reply(self, chat_id: str, reverse_id: int) -> ButtonReply:
        """✏️ Twist on a finished reverse — use the stored line or ask."""
        from app.prompts.reverse_prompt import load_reference_frames

        try:
            row = self.api_get(f'/api/prompts/reverse/{reverse_id}', None)
        except Exception as exc:
            if '404' in str(exc):
                return ButtonReply(f'No reverse #{reverse_id}.')
            return ButtonReply('Tower is unreachable right now — try again in a minute.')
        if not isinstance(row, dict):
            return ButtonReply('Tower is unreachable right now — try again in a minute.')
        if str(row.get('status') or '') != 'done' or not (row.get('prompt_text') or '').strip():
            return ButtonReply('The original prompt is not ready yet — wait for the reverse to finish.')
        status = str(row.get('twist_status') or '')
        if status == 'stills' or (
            status == 'running'
            and load_reference_frames(row.get('twist_frames'))
            and not row.get('twist_video_key')
        ):
            return self._stills_ready_reply(row)
        if status in ('queued', 'running', 'omni'):
            self._kick_watcher(self.on_twist_started, chat_id, reverse_id)
            if not self._claim_once(STATE_TWIST_ANNOUNCED.format(rid=reverse_id)):
                return ButtonReply('')
            if status == 'omni':
                return ButtonReply(f'💥 Twist #{reverse_id} — Gemini Omni is already making the video.')
            return ButtonReply(f'💥✏️ Twist for #{reverse_id} is already running — the twisted prompt and stills land here.')
        idea = (row.get('twist_text') or '').strip()
        if not idea:
            self.sessions.set_state(STATE_AWAIT_TWIST_APPLY.format(chat=chat_id), str(reverse_id))
            return ButtonReply(TWIST_ASK)
        return self._start_twist(chat_id, reverse_id, idea)

    def _start_twist(self, chat_id: str, reverse_id: int, twist: str) -> ButtonReply:
        try:
            row = self.api_post(f'/api/prompts/reverse/{reverse_id}/twist', {'twist': twist})
        except Exception as exc:
            text = str(exc)
            if '409' in text:
                return ButtonReply('The original prompt is not ready yet — wait for the reverse to finish.')
            if '422' in text:
                return ButtonReply('Send a twist line — one imaginative sentence.')
            logger.exception('twist request failed')
            return ButtonReply('Tower could not start the twist — check /health and try again.')
        if not isinstance(row, dict):
            return ButtonReply('Tower could not start the twist — check /health and try again.')
        if row.get('twist_status') == 'failed' and row.get('twist_error'):
            return ButtonReply(f"Twist failed to queue: {row.get('twist_error')}")
        self.sessions.set_state(STATE_TWIST_STILLS_DELIVERED.format(rid=int(reverse_id)), '')
        self.sessions.set_state(STATE_TWIST_DELIVERED.format(rid=int(reverse_id)), '')
        self.sessions.set_state(STATE_TWIST_ANNOUNCED.format(rid=int(reverse_id)), '')
        self._kick_watcher(self.on_twist_started, chat_id, reverse_id)
        self.sessions.set_state(STATE_TWIST_ANNOUNCED.format(rid=int(reverse_id)), '1')
        return ButtonReply(
            f'💥✏️ Twist #{reverse_id} started — Gemini rewrites every beat, '
            'then each cut frame goes through text+image→image. Usually 3–8 minutes.'
        )

    def omni_reply(self, chat_id: str, reverse_id: int) -> ButtonReply:
        """▶ Start the Twist — Omni only, after stills exist."""
        try:
            row = self.api_post(f'/api/prompts/reverse/{reverse_id}/omni', {})
        except Exception as exc:
            text = str(exc)
            if '404' in text:
                return ButtonReply(f'No reverse #{reverse_id}.')
            if '409' in text:
                return ButtonReply('Twisted stills are not ready yet — wait for the images, then tap Start the Twist.')
            logger.exception('omni request failed')
            return ButtonReply('Tower could not start Omni — check /health and try again.')
        if not isinstance(row, dict):
            return ButtonReply('Tower could not start Omni — check /health and try again.')
        if row.get('twist_status') == 'failed' and row.get('twist_error'):
            return ButtonReply(f"Omni failed to queue: {row.get('twist_error')}")
        self._kick_watcher(self.on_twist_started, chat_id, reverse_id)
        if not self._claim_once(STATE_TWIST_ANNOUNCED.format(rid=reverse_id)):
            return ButtonReply('')
        return ButtonReply(f'💥 Twist #{reverse_id} — Gemini Omni is making the video. About 2–6 min.')

    def _stills_ready_reply(self, row: dict[str, Any]) -> ButtonReply:
        from app.prompts.reverse_prompt import load_reference_frames

        rid = int(row.get('id') or 0)
        n = len(load_reference_frames(row.get('twist_frames')))
        return ButtonReply(
            f'🖼 {n} twisted stills ready. Tap Images (4 at a time), then {START_TWIST} for the video.',
            self._stills_ready_keyboard(rid),
        )

    def _stills_ready_keyboard(self, reverse_id: int) -> list[list[tuple[str, str]]]:
        return [
            [('🖼 Images', f'pt:timgs:{reverse_id}')],
            [(START_TWIST, f'pt:omni:{reverse_id}')],
        ]

    def maybe_take_vision_model(self, chat_id: str, raw: str) -> ButtonReply:
        """Owner tapped Gemini / GPT-6 Astra / Claude Fable 5 after the title.
        A second tap must reuse the link we already have — never ask again."""
        from app.prompts.reverse_prompt import resolve_vision_engine, vision_key_missing, vision_label, ReverseError

        url = self.sessions.get_state(STATE_PENDING_URL.format(chat=chat_id), '') or None
        has_video = bool(self.sessions.get_state(STATE_VIDEO.format(chat=chat_id), ''))
        try:
            engine = resolve_vision_engine(raw)
        except ReverseError:
            return ButtonReply(MODEL_ASK, MODEL_BUTTONS)
        missing = vision_key_missing(engine)
        if missing:
            return ButtonReply(
                f'{vision_label(engine)} is not ready: {missing}\nPick another model.',
                MODEL_BUTTONS,
            )
        if url or has_video:
            title = self.sessions.get_state(STATE_PENDING_TITLE.format(chat=chat_id), '') or None
            twist = self.sessions.get_state(STATE_PENDING_TWIST.format(chat=chat_id), '') or None
            self.sessions.set_state(STATE_AWAIT_MODEL.format(chat=chat_id), '')
            self.sessions.set_state(STATE_PENDING_TITLE.format(chat=chat_id), '')
            self.sessions.set_state(STATE_PENDING_TWIST.format(chat=chat_id), '')
            self.sessions.set_state(STATE_PENDING_URL.format(chat=chat_id), '')
            if has_video:
                return self.video_reply(chat_id, title=title, vision_engine=engine, twist=twist)
            return self._start_reverse(chat_id, source_url=url, title=title, vision_engine=engine, twist=twist)
        resumed = self._resume_last_reverse(chat_id)
        if resumed is not None:
            return resumed
        self.sessions.set_state(STATE_AWAIT_URL.format(chat=chat_id), '1')
        return ButtonReply(REVERSE_ASK)

    def _resume_last_reverse(self, chat_id: str) -> ButtonReply | None:
        raw = self.sessions.get_state(STATE_LAST_REVERSE.format(chat=chat_id), '')
        if not raw.isdigit():
            return None
        reverse_id = int(raw)
        try:
            row = self.api_get(f'/api/prompts/reverse/{reverse_id}', None)
        except Exception:
            return None
        if not isinstance(row, dict):
            return None
        status = str(row.get('status') or '')
        if status in {'queued', 'downloading', 'describing', 'composing'}:
            self._kick_watcher(self.on_reverse_started, chat_id, reverse_id)
            if not self._claim_once(STATE_REVERSE_ANNOUNCED.format(rid=reverse_id)):
                return ButtonReply('')
            return ButtonReply(REVERSE_STARTED)
        if status == 'done':
            return ButtonReply(
                f'Reverse #{reverse_id} is already done — tap Images / Show prompt / Twist below.',
                self._reverse_done_keyboard(row, offer_twist=True),
            )
        return None

    def video_reply(
        self,
        chat_id: str,
        title: str | None = None,
        vision_engine: str | None = None,
        twist: str | None = None,
    ) -> ButtonReply:
        """Forwarded video: ask for the header first, then the model.

        When ``on_reverse_upload`` is wired, reply instantly and download in
        the background — never hold the chat on a multi-MB Telegram fetch.
        """
        if not title:
            return self._ask_title(chat_id)
        file_id = self.sessions.get_state(STATE_VIDEO.format(chat=chat_id), '')
        if not file_id or self.download_photo is None:
            return ButtonReply('I could not read that video — send it as a video (not a file), or send the link.')
        if self.on_reverse_upload is not None:
            try:
                self.on_reverse_upload(
                    str(chat_id),
                    title=title,
                    vision_engine=vision_engine,
                    twist=twist,
                )
            except Exception:
                logger.exception('reverse upload kick failed chat=%s', chat_id)
                return ButtonReply('Tower could not start the reverse prompt — check /health and try again.')
            return ButtonReply(REVERSE_STARTED)
        try:
            data, _content_type = self.download_photo(file_id)
        except Exception as exc:
            logger.exception('telegram video download failed')
            hint = ' (Telegram lets bots download files up to 20 MB — send the link instead)' if 'too big' in str(exc).lower() or '400' in str(exc) else ''
            return ButtonReply(f'Could not download the video from Telegram{hint}.')
        self.sessions.set_state(STATE_VIDEO.format(chat=chat_id), '')
        return self._start_reverse(chat_id, video=data, title=title, vision_engine=vision_engine, twist=twist)

    def finish_video_upload(
        self,
        chat_id: str,
        *,
        title: str | None = None,
        vision_engine: str | None = None,
        twist: str | None = None,
    ) -> ButtonReply:
        """Background path: download the pending Telegram file, then queue."""
        file_id = self.sessions.get_state(STATE_VIDEO.format(chat=chat_id), '')
        if not file_id or self.download_photo is None:
            self.sessions.set_state(STATE_AWAIT_URL.format(chat=chat_id), '1')
            return ButtonReply(REVERSE_ASK)
        try:
            data, _content_type = self.download_photo(file_id)
        except Exception as exc:
            logger.exception('telegram video download failed')
            hint = (
                ' (Telegram lets bots download files up to 20 MB — send the link instead)'
                if 'too big' in str(exc).lower() or '400' in str(exc) else ''
            )
            return ButtonReply(f'Could not download the video from Telegram{hint}.')
        self.sessions.set_state(STATE_VIDEO.format(chat=chat_id), '')
        return self._start_reverse(
            chat_id, video=data, title=title, vision_engine=vision_engine, twist=twist,
        )

    def _ask_title(self, chat_id: str, *, source_url: str | None = None) -> ButtonReply:
        self.sessions.set_state(STATE_AWAIT_URL.format(chat=chat_id), '')
        self.sessions.set_state(STATE_AWAIT_TITLE.format(chat=chat_id), '1')
        if source_url:
            self.sessions.set_state(STATE_PENDING_URL.format(chat=chat_id), source_url)
        return ButtonReply(TITLE_ASK)

    def _ask_vision_model(self, chat_id: str) -> ButtonReply:
        self.sessions.set_state(STATE_AWAIT_MODEL.format(chat=chat_id), '1')
        return ButtonReply(MODEL_ASK, MODEL_BUTTONS)

    def _start_reverse(
        self,
        chat_id: str,
        *,
        source_url: str | None = None,
        video: bytes | None = None,
        title: str | None = None,
        vision_engine: str | None = None,
        twist: str | None = None,
    ) -> ButtonReply:
        payload: dict[str, Any] = {'chat_id': str(chat_id)}
        if title:
            payload['title'] = title
        if vision_engine:
            payload['vision_engine'] = vision_engine
        if twist:
            payload['twist'] = twist
        if video is not None:
            payload['video_base64'] = base64.b64encode(video).decode('ascii')
        elif (source_url or '').strip():
            payload['source_url'] = source_url
        else:
            self.sessions.set_state(STATE_AWAIT_URL.format(chat=chat_id), '1')
            return ButtonReply(REVERSE_ASK)
        try:
            row = self.api_post('/api/prompts/reverse', payload)
        except Exception as exc:
            text = str(exc)
            if '422' in text:
                return ButtonReply('That link is not an Instagram reel, a Pinterest pin or a direct video — send one of those.')
            if '413' in text:
                return ButtonReply('That video is too large (80 MB max) — send a shorter clip or the link.')
            logger.exception('reverse request failed')
            return ButtonReply('Tower could not start the reverse prompt — check /health and try again.')
        self.sessions.set_state(STATE_AWAIT_URL.format(chat=chat_id), '')
        if not isinstance(row, dict) or not row.get('id'):
            return ButtonReply('Tower could not start the reverse prompt — check /health and try again.')
        self.sessions.set_state(STATE_LAST_REVERSE.format(chat=chat_id), str(row['id']))
        if row.get('status') == 'failed':
            return ButtonReply(f"Reverse prompt failed to queue: {row.get('error') or 'unknown error'}")
        self._clear_delivery(int(row['id']))
        self._kick_watcher(self.on_reverse_started, chat_id, int(row['id']))
        self.sessions.set_state(STATE_REVERSE_ANNOUNCED.format(rid=int(row['id'])), '1')
        return ButtonReply(REVERSE_STARTED)

    def retry_reverse_reply(self, chat_id: str, reverse_id: int) -> ButtonReply:
        """Owner tapped Retry on a reverse that never reached Gemini."""
        try:
            row = self.api_post(f'/api/prompts/reverse/{reverse_id}/retry', {})
        except Exception as exc:
            if '404' in str(exc):
                return ButtonReply(f'No reverse #{reverse_id}.')
            if '409' in str(exc):
                return ButtonReply(f'Reverse #{reverse_id} is already finished — no retry needed.')
            logger.exception('reverse retry failed')
            return ButtonReply('Tower could not retry — check /health and try again.')
        if not isinstance(row, dict):
            return ButtonReply('Tower could not retry — check /health and try again.')
        if row.get('status') == 'failed':
            return ButtonReply(f"Retry failed: {row.get('error') or 'unknown error'}")
        self._clear_delivery(reverse_id)
        self._kick_watcher(self.on_reverse_started, chat_id, reverse_id)
        if not self._claim_once(STATE_REVERSE_ANNOUNCED.format(rid=reverse_id)):
            return ButtonReply('')
        return ButtonReply(
            f"🔄 Reverse #{reverse_id} kicked again — waiting for the clip, then Gemini. "
            'Forward the video file if Instagram keeps hiding it.',
        )

    def watch_reverse(
        self,
        chat_id: str,
        reverse_id: int,
        *,
        poll_s: float = REVERSE_POLL_S,
        max_wait_s: float = REVERSE_MAX_WAIT_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> str:
        """Poll until done — stay silent mid-flight. One message only at the end.

        The start tap already said Workflow Started…. No processing / download /
        heartbeat spam. Auto-retry quietly if the worker never picks up.
        """
        waited = 0.0
        requeued = False
        while True:
            try:
                row = self.api_get(f'/api/prompts/reverse/{reverse_id}', None)
            except Exception:
                row = None
            if isinstance(row, dict):
                status = str(row.get('status') or '')
                if status == 'queued' and waited >= 45 and not requeued:
                    requeued = True
                    try:
                        self.api_post(f'/api/prompts/reverse/{reverse_id}/retry', {})
                    except Exception:
                        logger.exception('auto-retry reverse failed id=%s', reverse_id)
                if status == 'done':
                    self._deliver_reverse(chat_id, row, sleep=sleep)
                    return 'done'
                if status == 'failed':
                    text = f"❌ Reverse prompt #{reverse_id} failed: {_reverse_fail_text(row)}"
                    if self.send_text:
                        self.send_text(chat_id, text)
                    return 'failed'
            if waited >= max_wait_s:
                text = (
                    f'⏳ Reverse #{reverse_id} is still going after '
                    f'{int(max_wait_s // 60)} min — paste the link again anytime.'
                )
                if self.send_text:
                    self.send_text(chat_id, text)
                return 'timeout'
            sleep(poll_s)
            waited += poll_s

    def _reverse_done_keyboard(self, row: dict[str, Any], *, offer_twist: bool = True) -> list[list[tuple[str, str]]]:
        """Play + Images / Show / Copy / Twist. No Save clip / Save reel (Ashok 2026-09-12)."""
        keyboard: list[list[tuple[str, str]]] = []
        # Save twist only when a twisted MP4 exists — never Save clip / Save reel.
        keyboard.extend(save_keyboard(('⬇️ Save twist', row.get('twist_video_url'))))
        rid = row.get('id')
        if rid is None:
            return keyboard
        play_row: list[tuple[str, str]] = []
        if row.get('video_key'):
            play_row.append(('▶️ Clip', f'pt:playclip:{int(rid)}'))
        if row.get('reel_key'):
            play_row.append(('▶️ Reel', f'pt:playreel:{int(rid)}'))
        if row.get('twist_video_key'):
            play_row.append(('▶️ Twist', f'pt:playtwist:{int(rid)}'))
        if play_row:
            keyboard.append(play_row)
        from app.prompts.reverse_prompt import load_reference_frames

        kind = 'timgs' if load_reference_frames(row.get('twist_frames')) else 'imgs'
        keyboard.append([('🖼 Images', f'pt:{kind}:{int(rid)}')])
        keyboard.append([
            ('Show prompt', f'pt:show:{int(rid)}'),
            ('Copy prompt', f'pt:copy:{int(rid)}'),
        ])
        if offer_twist:
            keyboard.append([('💥 Twist', f'pt:twist:{int(rid)}')])
        elif not row.get('twist_video_key') and load_reference_frames(row.get('twist_frames')):
            keyboard.append([(START_TWIST, f'pt:omni:{int(rid)}')])
        return keyboard

    def _offer_saves(self, chat_id: str, pairs: tuple[tuple[str, str | None], ...]) -> None:
        """URL buttons that force Save As — daily-deck renders only."""
        keyboard = save_keyboard(*pairs)
        if not keyboard:
            return
        text = '⬇️ Tap to SAVE the file on your phone (not play in the browser).'
        if self.send_keyboard:
            self.send_keyboard(chat_id, text, keyboard)
            return
        if self.send_text:
            lines = [text] + [f'{label}: {href}' for row in keyboard for label, href in row]
            self.send_text(chat_id, '\n'.join(lines))

    def _done_caption(self, row: dict[str, Any], *, offer_twist: bool = True) -> str:
        """One word. Timing + twist ask live in buttons / logs, not the chat (Ashok 2026-09-12)."""
        del row, offer_twist
        return READY_CAPTION

    def _offer_reverse_done(
        self, chat_id: str, row: dict[str, Any], *, offer_twist: bool = True,
    ) -> None:
        """Exactly one message: status + buttons. Never dump prompt/images/video."""
        rid = int(row.get('id') or 0)
        key = (
            STATE_REVERSE_DELIVERED.format(rid=rid)
            if offer_twist
            else STATE_TWIST_DELIVERED.format(rid=rid)
        )
        if rid and not self._claim_once(key):
            return
        keyboard = self._reverse_done_keyboard(row, offer_twist=offer_twist)
        text = self._done_caption(row, offer_twist=offer_twist)
        if self.send_keyboard:
            self.send_keyboard(chat_id, text, keyboard)
            return
        if self.send_text:
            self.send_text(chat_id, text)

    def _prompt_body(self, row: dict[str, Any]) -> str:
        if str(row.get('twist_status') or '') == 'done' and (row.get('twist_prompt') or '').strip():
            return str(row.get('twist_prompt') or '').strip()
        return str(row.get('prompt_text') or '').strip()

    def _prompt_text_reply(self, chat_id: str, reverse_id: int, *, copy: bool) -> ButtonReply:
        try:
            row = self.api_get(f'/api/prompts/reverse/{reverse_id}', None)
        except Exception as exc:
            if '404' in str(exc):
                return ButtonReply(f'No reverse #{reverse_id}.')
            return ButtonReply('Tower is unreachable right now — try again in a minute.')
        if not isinstance(row, dict):
            return ButtonReply('Tower is unreachable right now — try again in a minute.')
        body = self._prompt_body(row)
        if not body:
            return ButtonReply('The prompt is not ready yet — wait for the reverse to finish.')
        if copy and self.send_document_bytes:
            name = f'prompt-{reverse_id}.txt'
            try:
                try:
                    self.send_document_bytes(
                        chat_id, body.encode('utf-8'), filename=name, caption='Copy prompt',
                    )
                except TypeError:
                    self.send_document_bytes(chat_id, body.encode('utf-8'), name, 'Copy prompt')
                return ButtonReply('Prompt file sent — open it to copy.')
            except Exception:
                logger.exception('copy-prompt document failed id=%s', reverse_id)
        head = '' if copy else f'📝 Prompt #{reverse_id}\n'
        chunks = list(_chunks(body, TELEGRAM_TEXT_LIMIT - len(head)))
        if not chunks:
            return ButtonReply('The prompt is empty.')
        first = ButtonReply(head + chunks[0])
        if self.send_text:
            for extra in chunks[1:]:
                self.send_text(chat_id, extra)
        elif len(chunks) > 1:
            first = ButtonReply(head + '\n'.join(chunks))
        return first

    def _send_video_file(self, chat_id: str, key: str | None, caption: str, *, rid=None) -> bool:
        """Telegram sendVideo — only after the owner taps Play."""
        if not key or not self.fetch_asset or not self.send_video_bytes:
            return False
        try:
            self.send_video_bytes(chat_id, self.fetch_asset(key), caption)
            return True
        except Exception:
            logger.exception('video upload failed id=%s key=%s', rid, key)
            return False

    def play_video_reply(self, chat_id: str, reverse_id: int, *, kind: str) -> ButtonReply:
        """▶️ Clip / Reel / Twist — one video, only on tap."""
        try:
            row = self.api_get(f'/api/prompts/reverse/{reverse_id}', None)
        except Exception as exc:
            if '404' in str(exc):
                return ButtonReply(f'No reverse #{reverse_id}.')
            return ButtonReply('Tower is unreachable right now — try again in a minute.')
        if not isinstance(row, dict):
            return ButtonReply('Tower is unreachable right now — try again in a minute.')
        key_field = {
            'playclip': 'video_key',
            'playreel': 'reel_key',
            'playtwist': 'twist_video_key',
        }.get(kind, '')
        label = {'playclip': 'clip', 'playreel': 'reel', 'playtwist': 'twist video'}.get(kind, 'video')
        key = row.get(key_field) if key_field else None
        if not key:
            err = row.get('reel_error') if kind == 'playreel' else row.get('twist_video_error')
            return ButtonReply(err or f'No {label} ready for #{reverse_id}.')
        caption = f'🎞 Reverse #{reverse_id} — {label}. Tap to save on your phone.'
        if self._send_video_file(chat_id, key, caption, rid=reverse_id):
            return ButtonReply(f'{label.capitalize()} sent.')
        return ButtonReply(f'Could not send the {label} — try the Save button instead.')

    def _deliver_reverse(
        self, chat_id: str, row: dict[str, Any], *, sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """One message with buttons. Clip / reel / prompt / images wait for a tap."""
        self._offer_reverse_done(chat_id, row, offer_twist=True)

    def _send_reference_document(
        self, chat_id: str, data: bytes, filename: str, caption: str, *, sleep: Callable[[float], None],
    ) -> None:
        last: BaseException | None = None
        for attempt in range(REF_SEND_TRIES):
            try:
                try:
                    self.send_document_bytes(chat_id, data, filename=filename, caption=caption)
                except TypeError:
                    self.send_document_bytes(chat_id, data, filename, caption)
                return
            except Exception as exc:
                last = exc
                wait = retry_after_s(exc) or (0.7 * (attempt + 1))
                logger.warning('reference frame send %s try %s failed: %s', filename, attempt + 1, exc)
                sleep(wait)
        raise RuntimeError(str(last) if last else 'sendDocument failed')

    def _offer_timing(self, chat_id: str, row: dict[str, Any]) -> None:
        from app.prompts.gen_timings import format_line

        line = format_line(row.get('timings'))
        if line and self.send_text:
            self.send_text(chat_id, line)

    def images_reply(
        self,
        chat_id: str,
        reverse_id: int,
        *,
        kind: str = 'cut',
        offset: int = 0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> ButtonReply:
        """On demand: 4 frames, then More. Never dump all 14."""
        from app.prompts.reverse_prompt import load_reference_frames

        try:
            row = self.api_get(f'/api/prompts/reverse/{reverse_id}', None)
        except Exception as exc:
            if '404' in str(exc):
                return ButtonReply(f'No reverse #{reverse_id}.')
            return ButtonReply('Tower is unreachable right now — try again in a minute.')
        if not isinstance(row, dict):
            return ButtonReply('Tower is unreachable right now — try again in a minute.')
        field = 'twist_frames' if kind == 'twist' else 'ref_frames'
        frames = load_reference_frames(row.get(field))
        label = 'twisted cut frames' if kind == 'twist' else 'cut-reference frames'
        if not frames:
            err = row.get('twist_error') if kind == 'twist' else row.get('ref_error')
            return ButtonReply(err or f'No {label} yet for #{reverse_id}.')
        offset = max(0, min(int(offset), len(frames)))
        page = frames[offset:offset + FRAME_PAGE]
        if not page:
            return ButtonReply(f'That is all {len(frames)} {label} for #{reverse_id}.')
        if not self.fetch_asset or not self.send_document_bytes:
            return ButtonReply(f'{len(frames)} {label} are stored — I cannot send files from here.')
        failed: list[str] = []
        for index, frame in enumerate(page, start=offset + 1):
            key = str(frame.get('key') or '')
            name = str(frame.get('filename') or f'frame-{index:02d}.jpg')
            t = frame.get('t')
            caption = f'{index}/{len(frames)} · {t:.2f}s' if isinstance(t, (int, float)) else f'{index}/{len(frames)}'
            try:
                self._send_reference_document(
                    chat_id, self.fetch_asset(key), name, caption, sleep=sleep,
                )
            except Exception as exc:
                logger.warning('paged frame send failed id=%s key=%s: %s', reverse_id, key, exc)
                failed.append(str(index))
            if index < offset + len(page):
                sleep(REF_SEND_GAP_S)
        nxt = offset + len(page)
        action = 'timgs' if kind == 'twist' else 'imgs'
        left = max(0, len(frames) - nxt)
        text = f'🖼 {offset + 1}–{nxt} of {len(frames)} {label} for #{reverse_id}.'
        if failed:
            text += f' {len(failed)} missed ({", ".join(failed)}).'
        if left:
            text += ' More images ▸'
            rows = [[('More images ▸', f'pt:{action}:{reverse_id}:{nxt}')]]
            if kind == 'twist' and not row.get('twist_video_key'):
                rows.append([(START_TWIST, f'pt:omni:{reverse_id}')])
            return ButtonReply(text, rows)
        extra = []
        if kind == 'twist' and not row.get('twist_video_key'):
            extra.append([(START_TWIST, f'pt:omni:{reverse_id}')])
        return ButtonReply(text, extra or None)

    def _deliver_frame_zip(
        self,
        chat_id: str,
        frames: list,
        *,
        rid,
        filename: str,
        label: str,
        sleep: Callable[[float], None],
    ) -> list[str]:
        """One ZIP — tap once, download all frames."""
        from app.prompts.reverse_twist import pack_frames_zip

        if self.send_text:
            self.send_text(
                chat_id,
                f'🖼 {len(frames)} {label} for #{rid} — one file, download all.',
            )
        if not self.fetch_asset or not self.send_document_bytes:
            if self.send_text:
                keys = ', '.join(str(frame.get('key') or '') for frame in frames[:14])
                self.send_text(chat_id, f'Frame keys: {keys}')
            return []
        data, failed = pack_frames_zip(frames, fetch=self.fetch_asset)
        packed = max(0, len(frames) - len(failed))
        if data:
            caption = f'{packed} {label} — tap to download all'
            try:
                self._send_reference_document(chat_id, data, filename, caption, sleep=sleep)
            except Exception as exc:
                logger.warning('frame zip upload failed id=%s: %s', rid, exc)
                failed = [filename]
        elif not failed:
            failed = [filename]
        return failed

    def _deliver_reference_frames(
        self, chat_id: str, row: dict[str, Any], *, sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """One ZIP of cut frames AFTER the reel — not the storyboard."""
        from app.prompts.reverse_prompt import load_reference_frames

        frames = load_reference_frames(row.get('ref_frames'))
        rid = row.get('id')
        if not frames:
            if self.send_text and row.get('ref_error'):
                self.send_text(chat_id, f"⚠️ Cut-reference frames for #{rid}: {row.get('ref_error')}")
            return
        failed = self._deliver_frame_zip(
            chat_id,
            frames,
            rid=rid,
            filename=f'frames-{rid}.zip',
            label='cut-reference frames',
            sleep=sleep,
        )
        if failed and self.send_text:
            self.send_text(
                chat_id,
                f'⚠️ {len(failed)} of {len(frames)} cut frames did not arrive ({", ".join(failed[:8])}). '
                'Say so and I will resend them.',
            )

    def watch_twist(
        self,
        chat_id: str,
        reverse_id: int,
        *,
        poll_s: float = REVERSE_POLL_S,
        max_wait_s: float = TWIST_MAX_WAIT_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> str:
        """Silent mid-flight. One message when stills are ready, done, or failed."""
        from app.prompts.reverse_prompt import load_reference_frames

        waited = 0.0
        while True:
            try:
                row = self.api_get(f'/api/prompts/reverse/{reverse_id}', None)
            except Exception:
                row = None
            if isinstance(row, dict):
                status = str(row.get('twist_status') or '')
                stills = load_reference_frames(row.get('twist_frames'))
                waiting = (
                    bool(stills)
                    and not row.get('twist_video_key')
                    and status in {'stills', 'running'}
                )
                if waiting:
                    self._offer_stills_gate(chat_id, row, stills)
                    return 'stills'
                if status == 'done':
                    self._deliver_twist(chat_id, row, sleep=sleep)
                    return 'done'
                if status == 'failed':
                    err = row.get('twist_error') or 'unknown error'
                    text = f'❌ Twist #{reverse_id} failed: {err}'
                    if self.send_text:
                        self.send_text(chat_id, text)
                    return 'failed'
            if waited >= max_wait_s:
                text = (
                    f'⏳ Twist #{reverse_id} is still running after {int(max_wait_s // 60)} min '
                    '— tap below when you want to continue.'
                )
                keyboard = [[(START_TWIST, f'pt:omni:{reverse_id}')]]
                if self.send_keyboard:
                    self.send_keyboard(chat_id, text, keyboard)
                elif self.send_text:
                    self.send_text(chat_id, text)
                return 'timeout'
            sleep(poll_s)
            waited += poll_s

    def _offer_stills_gate(self, chat_id: str, row: dict[str, Any], stills: list) -> None:
        rid = int(row.get('id') or 0)
        if rid and not self._claim_once(STATE_TWIST_STILLS_DELIVERED.format(rid=rid)):
            return
        text = (
            f'🖼 {len(stills)} twisted stills ready. Tap Images (4 at a time), '
            f'then {START_TWIST} for the video.'
        )
        keyboard = self._stills_ready_keyboard(rid)
        if self.send_keyboard:
            self.send_keyboard(chat_id, text, keyboard)
            return
        if self.send_text:
            self.send_text(chat_id, text)

    def _deliver_twist(
        self, chat_id: str, row: dict[str, Any], *, sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """One message — twisted video waits for ▶️ Twist."""
        self._offer_reverse_done(chat_id, row, offer_twist=False)

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
                            f"📇 Preview card for prompt #{render.get('prompt_id')} — "
                            'the post-ready reel (video in the card, storyboard + scrolling prompt) follows.',
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
        """The reel (clip inside the card template) is the post asset. When
        the reel could not be composed, the raw clip goes out with the
        reason, so a missing ffmpeg never hides a finished video."""
        prompt_id = render.get('prompt_id')
        model = f" · {render['model']}" if render.get('model') else ''
        clip_save = save_url(render.get('video_url'))
        if render.get('reel_key'):
            caption = (
                f"🎬 Prompt #{prompt_id} — reel ready, post this{model}\n"
                f"Save clip: {clip_save}"
            ).strip()
            key = render.get('reel_key')
        else:
            why = render.get('reel_error') or 'unknown reason'
            caption = (
                f"🎬 Prompt #{prompt_id} — raw clip ready{model}\n"
                f"⚠️ Reel not composed: {why}\n"
                f"Save clip: {clip_save}"
            ).strip()
            key = render.get('video_key')
        if key and self.fetch_asset and self.send_video_bytes:
            try:
                self.send_video_bytes(chat_id, self.fetch_asset(key), caption)
                self._offer_saves(chat_id, (
                    ('⬇️ Save clip', render.get('video_url')),
                    ('⬇️ Save reel', render.get('reel_url')),
                ))
                return
            except Exception:
                logger.exception('video upload failed render=%s', render.get('id'))
        if self.send_text:
            self.send_text(chat_id, caption)
        self._offer_saves(chat_id, (
            ('⬇️ Save clip', render.get('video_url')),
            ('⬇️ Save reel', render.get('reel_url')),
        ))

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

    def _reverse_pending(self, chat_id: str) -> bool:
        keys = (
            STATE_AWAIT_URL, STATE_AWAIT_TITLE, STATE_AWAIT_TWIST,
            STATE_AWAIT_TWIST_APPLY, STATE_AWAIT_MODEL, STATE_PENDING_URL,
            STATE_PENDING_TITLE, STATE_PENDING_TWIST, STATE_VIDEO,
        )
        return any(self.sessions.get_state(key.format(chat=chat_id), '') for key in keys)

    def _clear_pending(self, chat_id: str) -> None:
        self.sessions.set_state(STATE_AWAIT_IMAGE.format(chat=chat_id), '')
        self.sessions.set_state(STATE_PHOTO.format(chat=chat_id), '')
        self.sessions.set_state(STATE_AWAIT_URL.format(chat=chat_id), '')
        self.sessions.set_state(STATE_AWAIT_TITLE.format(chat=chat_id), '')
        self.sessions.set_state(STATE_AWAIT_TWIST.format(chat=chat_id), '')
        self.sessions.set_state(STATE_AWAIT_TWIST_APPLY.format(chat=chat_id), '')
        self.sessions.set_state(STATE_AWAIT_MODEL.format(chat=chat_id), '')
        self.sessions.set_state(STATE_PENDING_URL.format(chat=chat_id), '')
        self.sessions.set_state(STATE_PENDING_TITLE.format(chat=chat_id), '')
        self.sessions.set_state(STATE_PENDING_TWIST.format(chat=chat_id), '')
        self.sessions.set_state(STATE_VIDEO.format(chat=chat_id), '')


def retry_after_s(exc: BaseException) -> float | None:
    """Telegram flood-wait: 'Too Many Requests: retry after 4'."""
    match = RETRY_AFTER_RE.search(str(exc))
    if match:
        return float(match.group(1))
    headers = getattr(getattr(exc, 'headers', None), 'get', None)
    if callable(headers):
        raw = headers('Retry-After')
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    return None


def _as_reply(value: str | ButtonReply) -> ButtonReply:
    return value if isinstance(value, ButtonReply) else ButtonReply(value)


def _reverse_fail_text(row: dict[str, Any]) -> str:
    """Never show Kling's 'video model failed' costume for a Gemini refuse."""
    raw = str(row.get('error') or 'unknown error')
    if 'e001' in raw.lower() and 'gemini could not read' not in raw.lower():
        return (
            'Gemini could not read this clip (E001). '
            'Pinterest/HLS often needs an H.264 remux — forward the video file '
            'or paste another link. Astra/Fable also work.'
        )
    if raw.lower().startswith('video model failed') and 'e001' in raw.lower():
        return (
            'Gemini could not read this clip (E001). '
            'Forward the video file or paste another link and pick Gemini again.'
        )
    return raw


def _seconds(value: Any) -> str:
    try:
        return f'{float(value):.1f}s'
    except (TypeError, ValueError):
        return 'length unknown'


def _chunks(text: str, size: int) -> list[str]:
    """Split on line breaks so a timestamped segment is never cut mid-way
    when the prompt is longer than one Telegram message."""
    size = max(size, 200)
    if len(text) <= size:
        return [text]
    out: list[str] = []
    current = ''
    for line in text.split('\n'):
        while len(line) > size:
            out.append(line[:size])
            line = line[size:]
        if len(current) + len(line) + 1 > size and current:
            out.append(current)
            current = line
        else:
            current = f'{current}\n{line}' if current else line
    if current:
        out.append(current)
    return out


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
