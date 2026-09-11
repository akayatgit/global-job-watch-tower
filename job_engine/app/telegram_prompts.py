"""Prompt Tower on Telegram — Ashok's daily top-10 deck (owner-only).

Everything here is deterministic formatting over the tower API: the list,
the full prompt, the ⭐ rating, the "📸 product image → ✅ make video" flow,
the render watcher that uploads the finished MP4 + Instagram card back
into the chat, and reverse prompt (`/igtovid` · `/pintovid`) which delivers
the Gemini-authored timestamped prompt verbatim. No model composes job
facts; reverse prompt is the one place a model authors a generation prompt.

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
# Reverse prompt (2026-09-10): /igtovid · /pintovid → waiting for the URL
# (or the video file itself) → tower row polled by watch_reverse.
STATE_AWAIT_URL = 'prompt_await_url:{chat}'
STATE_AWAIT_TITLE = 'prompt_await_title:{chat}'
STATE_AWAIT_MODEL = 'prompt_await_reverse_model:{chat}'
STATE_PENDING_URL = 'prompt_pending_reverse_url:{chat}'
STATE_PENDING_TITLE = 'prompt_pending_reverse_title:{chat}'
STATE_VIDEO = 'pending_prompt_video:{chat}'
REVERSE_COMMANDS = frozenset({'igtovid', 'pintovid', 'pintovideo', 'reverseprompt'})
REVERSE_POLL_S = 15
REVERSE_MAX_WAIT_S = 25 * 60
TELEGRAM_TEXT_LIMIT = 3900
REVERSE_USAGE = (
    'Send me the Instagram reel or Pinterest pin link (or forward the video file itself). '
    "Then I'll ask for the header title, then which model reverses it "
    '(Gemini · GPT-6 Astra · Claude Fable 5). I cut the cinematic reel — '
    '9:16 clip · storyboard · scrolling prompt.'
)
TITLE_ASK = (
    'What should the header say? (e.g. CINEMATIC AI AD)\n'
    'The footer is always:\n'
    'Comment “AI” to get\n'
    'all the prompts'
)
MODEL_ASK = (
    'Which model should reverse this clip?\n'
    'The video file goes to the model you pick — Gemini, GPT-6 Astra, or Claude Fable 5.'
)
MODEL_BUTTONS = [
    [('Gemini', 'pt:revmodel:gemini')],
    [('GPT-6 Astra', 'pt:revmodel:astra')],
    [('Claude Fable 5', 'pt:revmodel:fable')],
    [('✖ Cancel', 'pt:cancel')],
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
        send_document_bytes: Callable[..., None] | None = None,
        send_text: Callable[[str, str], None] | None = None,
        on_render_started: Callable[[str, int], None] | None = None,
        on_reverse_started: Callable[[str, int], None] | None = None,
    ):
        self.sessions = sessions
        self.on_render_started = on_render_started
        self.on_reverse_started = on_reverse_started
        self.api_get = api_get
        self.api_post = api_post
        self.download_photo = download_photo
        self.fetch_asset = fetch_asset
        self.send_photo_bytes = send_photo_bytes
        self.send_video_bytes = send_video_bytes
        self.send_document_bytes = send_document_bytes
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
        if action == 'revmodel' and len(parts) >= 2:
            return self.maybe_take_vision_model(chat_id, parts[1])
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

        url = find_url(arg or '')
        if url:
            return self._ask_title(chat_id, source_url=url)
        self.sessions.set_state(STATE_AWAIT_URL.format(chat=chat_id), '1')
        return ButtonReply(f'🎞 Reverse prompt — {REVERSE_USAGE}', [[('✖ Cancel', 'pt:cancel')]])

    def maybe_take_url(self, chat_id: str, text: str) -> ButtonReply | None:
        """Owner text carrying an Instagram / Pinterest link: after /igtovid
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

    def maybe_take_vision_model(self, chat_id: str, raw: str) -> ButtonReply:
        """Owner tapped Gemini / GPT-6 Astra / Claude Fable 5 after the title."""
        from app.prompts.reverse_prompt import resolve_vision_engine, vision_key_missing, vision_label, ReverseError

        if self.sessions.get_state(STATE_AWAIT_MODEL.format(chat=chat_id), '') != '1':
            return ButtonReply('Send the link (or video) and the header title first.', [[('✖ Cancel', 'pt:cancel')]])
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
        title = self.sessions.get_state(STATE_PENDING_TITLE.format(chat=chat_id), '') or None
        url = self.sessions.get_state(STATE_PENDING_URL.format(chat=chat_id), '') or None
        has_video = bool(self.sessions.get_state(STATE_VIDEO.format(chat=chat_id), ''))
        self.sessions.set_state(STATE_AWAIT_MODEL.format(chat=chat_id), '')
        self.sessions.set_state(STATE_PENDING_TITLE.format(chat=chat_id), '')
        self.sessions.set_state(STATE_PENDING_URL.format(chat=chat_id), '')
        if has_video:
            return self.video_reply(chat_id, title=title, vision_engine=engine)
        if not url:
            return ButtonReply('Send the Instagram / Pinterest link first.', [[('✖ Cancel', 'pt:cancel')]])
        return self._start_reverse(chat_id, source_url=url, title=title, vision_engine=engine)

    def video_reply(self, chat_id: str, title: str | None = None, vision_engine: str | None = None) -> ButtonReply:
        """Forwarded video: ask for the header first, then the model, then upload + start."""
        if not title:
            return self._ask_title(chat_id)
        file_id = self.sessions.get_state(STATE_VIDEO.format(chat=chat_id), '')
        if not file_id or self.download_photo is None:
            return ButtonReply('I could not read that video — send it as a video (not a file), or send the link.')
        try:
            data, _content_type = self.download_photo(file_id)
        except Exception as exc:
            logger.exception('telegram video download failed')
            hint = ' (Telegram lets bots download files up to 20 MB — send the link instead)' if 'too big' in str(exc).lower() or '400' in str(exc) else ''
            return ButtonReply(f'Could not download the video from Telegram{hint}.')
        self.sessions.set_state(STATE_VIDEO.format(chat=chat_id), '')
        return self._start_reverse(chat_id, video=data, title=title, vision_engine=vision_engine)

    def _ask_title(self, chat_id: str, *, source_url: str | None = None) -> ButtonReply:
        self.sessions.set_state(STATE_AWAIT_URL.format(chat=chat_id), '')
        self.sessions.set_state(STATE_AWAIT_TITLE.format(chat=chat_id), '1')
        if source_url:
            self.sessions.set_state(STATE_PENDING_URL.format(chat=chat_id), source_url)
        return ButtonReply(f'🎞 Got it. {TITLE_ASK}', [[('✖ Cancel', 'pt:cancel')]])

    def _ask_vision_model(self, chat_id: str) -> ButtonReply:
        self.sessions.set_state(STATE_AWAIT_MODEL.format(chat=chat_id), '1')
        return ButtonReply(f'🎞 {MODEL_ASK}', MODEL_BUTTONS)

    def _start_reverse(
        self,
        chat_id: str,
        *,
        source_url: str | None = None,
        video: bytes | None = None,
        title: str | None = None,
        vision_engine: str | None = None,
    ) -> ButtonReply:
        from app.prompts.reverse_prompt import vision_label

        payload: dict[str, Any] = {'chat_id': str(chat_id)}
        if title:
            payload['title'] = title
        if vision_engine:
            payload['vision_engine'] = vision_engine
        if video is not None:
            payload['video_base64'] = base64.b64encode(video).decode('ascii')
        else:
            payload['source_url'] = source_url
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
        if row.get('status') == 'failed':
            return ButtonReply(f"Reverse prompt failed to queue: {row.get('error') or 'unknown error'}")
        if self.on_reverse_started is not None:
            try:
                self.on_reverse_started(str(chat_id), int(row['id']))
            except Exception:
                logger.exception('reverse watcher failed to start id=%s', row.get('id'))
        where = {'instagram': 'the Instagram reel', 'pinterest': 'the Pinterest pin', 'direct': 'the video link'}.get(
            str(row.get('platform') or ''), 'your video',
        )
        label = vision_label(vision_engine or row.get('vision_engine'))
        return ButtonReply(
            f"🎞 Reverse prompt #{row['id']} started from {where} · {label}. "
            'Downloading → timestamped prompt → 14 cut-reference frames → I cut the reel '
            '(clip · 6-frame storyboard · scrolling prompt). '
            'Usually 2–5 minutes; the reel, the prompt, then downloadable frames land here.',
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
        """Block until the reverse prompt finishes, deliver reel + prompt."""
        waited = 0.0
        announced: set[str] = set()
        while True:
            try:
                row = self.api_get(f'/api/prompts/reverse/{reverse_id}', None)
            except Exception:
                row = None
            if isinstance(row, dict):
                status = str(row.get('status') or '')
                if status == 'describing' and status not in announced and self.send_text:
                    from app.prompts.reverse_prompt import vision_label

                    announced.add(status)
                    label = vision_label(row.get('vision_engine'))
                    self.send_text(chat_id, f"⬇️ Reverse #{reverse_id}: clip downloaded ({_seconds(row.get('duration_s'))}) — {label} is watching it now.")
                if status == 'done':
                    self._deliver_reverse(chat_id, row)
                    return 'done'
                if status == 'failed':
                    if self.send_text:
                        self.send_text(chat_id, f"❌ Reverse prompt #{reverse_id} failed: {row.get('error') or 'unknown error'}")
                    return 'failed'
            if waited >= max_wait_s:
                if self.send_text:
                    self.send_text(chat_id, f'⏳ Reverse prompt #{reverse_id} is still running after {int(max_wait_s // 60)} min — I will stop watching.')
                return 'timeout'
            sleep(poll_s)
            waited += poll_s

    def _deliver_reverse(self, chat_id: str, row: dict[str, Any]) -> None:
        """Reel first (or the source clip with the reason), then the prompt
        text verbatim so it can be copied straight into the caption."""
        rid = row.get('id')
        model = f" · {row['model']}" if row.get('model') else ''
        catalogue = f" · catalogue #{row['prompt_id']}" if row.get('prompt_id') else ''
        if row.get('reel_key'):
            caption = f"🎞 Reverse prompt #{rid} — reel ready, post this{model}{catalogue}\nSource clip: {row.get('video_url') or ''}".strip()
            key = row.get('reel_key')
        else:
            caption = (
                f"🎞 Reverse prompt #{rid} — source clip{model}{catalogue}\n"
                f"⚠️ Reel not composed: {row.get('reel_error') or 'unknown reason'}\n{row.get('video_url') or ''}"
            ).strip()
            key = row.get('video_key')
        sent = False
        if key and self.fetch_asset and self.send_video_bytes:
            try:
                self.send_video_bytes(chat_id, self.fetch_asset(key), caption)
                sent = True
            except Exception:
                logger.exception('reverse video upload failed id=%s', rid)
        if not sent and self.send_text:
            self.send_text(chat_id, caption)
        if self.send_text:
            head = f"📝 Prompt #{rid} · keyword {row.get('keyword') or 'PRODUCT'}\n"
            for chunk in _chunks(str(row.get('prompt_text') or '(no prompt text)'), TELEGRAM_TEXT_LIMIT - len(head)):
                self.send_text(chat_id, head + chunk)
                head = ''
        self._deliver_reference_frames(chat_id, row)

    def _deliver_reference_frames(self, chat_id: str, row: dict[str, Any]) -> None:
        """Downloadable cut frames AFTER the prompt — not the reel storyboard."""
        from app.prompts.reverse_prompt import load_reference_frames

        frames = load_reference_frames(row.get('ref_frames'))
        rid = row.get('id')
        if not frames:
            if self.send_text and row.get('ref_error'):
                self.send_text(chat_id, f"⚠️ Cut-reference frames for #{rid}: {row.get('ref_error')}")
            return
        if self.send_text:
            self.send_text(
                chat_id,
                f'🖼 {len(frames)} cut-reference frames for #{rid} — download these '
                '(not the storyboard). Attach them with the prompt to recreate the clip.',
            )
        if not self.fetch_asset or not self.send_document_bytes:
            if self.send_text:
                keys = ', '.join(str(frame.get('key') or '') for frame in frames[:14])
                self.send_text(chat_id, f'Reference frame keys: {keys}')
            return
        for index, frame in enumerate(frames, start=1):
            key = str(frame.get('key') or '')
            if not key:
                continue
            t = frame.get('t')
            name = str(frame.get('filename') or f'cut-{index:02d}-{t}s.jpg')
            caption = f'{index}/{len(frames)} · {t:.2f}s' if isinstance(t, (int, float)) else f'{index}/{len(frames)}'
            try:
                self.send_document_bytes(
                    chat_id, self.fetch_asset(key), filename=name, caption=caption,
                )
            except TypeError:
                self.send_document_bytes(chat_id, self.fetch_asset(key), name, caption)
            except Exception:
                logger.exception('reference frame upload failed id=%s key=%s', rid, key)

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
        if render.get('reel_key'):
            caption = (
                f"🎬 Prompt #{prompt_id} — reel ready, post this{model}\n"
                f"Raw clip: {render.get('video_url') or ''}"
            ).strip()
            key = render.get('reel_key')
        else:
            why = render.get('reel_error') or 'unknown reason'
            caption = (
                f"🎬 Prompt #{prompt_id} — raw clip ready{model}\n"
                f"⚠️ Reel not composed: {why}\n{render.get('video_url') or ''}"
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
        self.sessions.set_state(STATE_AWAIT_URL.format(chat=chat_id), '')
        self.sessions.set_state(STATE_AWAIT_TITLE.format(chat=chat_id), '')
        self.sessions.set_state(STATE_AWAIT_MODEL.format(chat=chat_id), '')
        self.sessions.set_state(STATE_PENDING_URL.format(chat=chat_id), '')
        self.sessions.set_state(STATE_PENDING_TITLE.format(chat=chat_id), '')
        self.sessions.set_state(STATE_VIDEO.format(chat=chat_id), '')


def _as_reply(value: str | ButtonReply) -> ButtonReply:
    return value if isinstance(value, ButtonReply) else ButtonReply(value)


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
