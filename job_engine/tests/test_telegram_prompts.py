"""Prompt Tower on Telegram: /prompts deck, select → 📸 → ✅ make video,
⭐ rating, /promptperf, render watcher delivery, once-a-day push, and public
/igtovid · /pintovid for every user."""

from __future__ import annotations

import base64
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from unittest import mock

from app import config
from app.telegram_buttons import BTN_PREFIX, ButtonReply
from app.telegram_prompts import (
    PromptDeck, REVERSE_ASK, STATE_AWAIT_IMAGE, STATE_AWAIT_MODEL, STATE_AWAIT_TITLE, STATE_AWAIT_TWIST,
    STATE_AWAIT_TWIST_APPLY, STATE_AWAIT_URL, STATE_LAST_REVERSE, STATE_PENDING_TITLE, STATE_PENDING_URL,
    STATE_PHOTO, STATE_VIDEO,
)
from app.telegram_sessions import TelegramSessionStore
from scripts.telegram_job_bot import (
    PROMPT_COMMANDS, PROMPT_PHOTO_TAP, PROMPT_VIDEO_TAP,
    REVERSE_INTAKE_COMMANDS, JobMasterTelegramBot,
)
from tests.test_telegram_job_bot import FakeEngine, FakeTelegramAPI

TODAY = datetime.now(timezone.utc).date().isoformat()


def prompt_row(pid: int, **over):
    base = {
        'id': pid,
        'rank': pid,
        'title': f'Prompt number {pid}',
        'text': 'Create a 10-second vertical product film. ' * 12,
        'source': 'reddit',
        'author': 'smith',
        'category': 'perfume',
        'model_hint': 'veo',
        'final_score': 80.0 + pid,
        'ai_detail': 82.0,
        'ai_flow': 78.0,
        'heuristic_score': 90.0,
        'ai_reasons': ['lens stated', 'clear reveal'],
        'is_outlier': pid == 1,
        'baseline_mean': 70.0,
        'status': 'shortlisted',
        'rating': None,
        'source_url': 'https://www.reddit.com/r/aivideo/x/',
    }
    base.update(over)
    return base


class FakeTower:
    """Records API calls; serves canned prompt data."""

    def __init__(self, prompts: list[dict] | None = None):
        self.prompts = prompts if prompts is not None else [prompt_row(i) for i in range(1, 11)]
        self.gets: list[tuple[str, dict | None]] = []
        self.posts: list[tuple[str, dict | None]] = []
        self.render_status = {'id': 77, 'prompt_id': 3, 'status': 'queued', 'card_image_key': 'prompts/d/card.png'}
        self.reel_engine = {
            'engine': 'ffmpeg', 'ok': True, 'ffmpeg': '/home/user/anaconda3/envs/ai/bin/ffmpeg', 'ffprobe': None,
            'video_codec': 'libx264', 'audio': True, 'libs': {'av': None, 'cv2': '4.10.0'}, 'searched': ['/home/user/anaconda3/envs/ai/bin/ffmpeg'],
            'rejected': {}, 'hint': None,
        }
        self.fail_404 = False
        self.reverses: list[dict] = []
        self.reverse_status: dict | None = None

    def get(self, path: str, params: dict | None = None):
        self.gets.append((path, params))
        if path == '/api/prompts/reverse':
            return {'total': len(self.reverses), 'items': list(self.reverses)}
        if path.startswith('/api/prompts/reverse/'):
            rid = int(path.rsplit('/', 1)[1])
            if self.reverse_status and self.reverse_status.get('id') == rid:
                return dict(self.reverse_status)
            for row in self.reverses:
                if row['id'] == rid:
                    return dict(row)
            raise urllib.error.HTTPError(path, 404, 'Not Found', {}, None)
        if path == '/api/prompts/today':
            return {'day': (params or {}).get('day') or TODAY, 'total': len(self.prompts), 'prompts': self.prompts}
        if path == '/api/prompts/stats':
            return {
                'total': 40, 'scored': 38, 'pending_score': 2, 'posted': 3, 'exemplars': 4, 'outliers': 2,
                'by_source': {'reddit': 30, 'manual': 10}, 'shortlisted_today': 10, 'renders_done': 1,
                'reels_done': 1, 'reels_failed': 0, 'reel_engine': self.reel_engine,
                'baseline_mean': 74.5, 'baseline_std': 3.2, 'last_collected_at': datetime.now(timezone.utc).isoformat(),
            }
        if path.startswith('/api/prompts/renders/'):
            return dict(self.render_status)
        if path.startswith('/api/prompts/'):
            pid = int(path.rsplit('/', 1)[1])
            if self.fail_404:
                raise urllib.error.HTTPError(path, 404, 'Not Found', {}, None)
            for row in self.prompts:
                if row['id'] == pid:
                    return dict(row, text=row['text'] * 3)
            raise urllib.error.HTTPError(path, 404, 'Not Found', {}, None)
        raise AssertionError(path)

    def post(self, path: str, payload: dict | None = None):
        self.posts.append((path, payload))
        if path == '/api/prompts/scan':
            return {'queued': True}
        if path == '/api/prompts/ingest':
            return {'outcome': 'created', 'prompt': prompt_row(99, final_score=71.0, is_outlier=False)}
        if path.endswith('/rate'):
            return {'id': 3, 'rating': payload['rating'], 'exemplar': payload['rating'] >= 4}
        if path.endswith('/performance'):
            return {'performance_score': 31.0, 'exemplar': True}
        if path.endswith('/posted'):
            return {'status': 'posted'}
        if path.endswith('/render'):
            return {'id': 77, 'prompt_id': 3, 'status': 'queued'}
        if path.endswith('/retry') and '/reverse/' in path:
            rid = int(path.split('/')[-2])
            row = dict(self.reverse_status or {'id': rid, 'status': 'queued'})
            row.update({'id': rid, 'status': 'queued', 'error': None})
            self.reverse_status = row
            return row
        if path.endswith('/twist') and '/reverse/' in path:
            rid = int(path.split('/')[-2])
            idea = ((payload or {}).get('twist') or '').strip()
            row = dict(self.reverse_status or {'id': rid, 'status': 'done', 'prompt_text': 'draft'})
            row.update({
                'id': rid,
                'twist_text': idea or row.get('twist_text'),
                'twist_status': 'queued',
                'twist_error': None,
            })
            self.reverse_status = row
            return row
        if path == '/api/prompts/reverse':
            row = {
                'id': 11,
                'status': 'queued',
                'platform': 'instagram' if 'instagram' in str((payload or {}).get('source_url') or '') else (
                    'pinterest' if 'pinterest' in str((payload or {}).get('source_url') or '') or 'pin.it' in str((payload or {}).get('source_url') or '') else (
                        'direct' if (payload or {}).get('source_url') else 'upload'
                    )
                ),
                'source_url': (payload or {}).get('source_url'),
                'vision_engine': (payload or {}).get('vision_engine') or 'gemini',
                'error': None,
            }
            self.reverses.append(row)
            self.reverse_status = dict(row)
            return row
        raise AssertionError(path)


class DeckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = TelegramSessionStore(Path(self.tmp.name) / 's.db')
        self.tower = FakeTower()
        self.sent_photos: list[tuple[str, bytes, str]] = []
        self.sent_videos: list[tuple[str, bytes, str]] = []
        self.sent_docs: list[tuple[str, bytes, str, str]] = []
        self.texts: list[tuple[str, str]] = []
        self.keyboards: list[tuple[str, str, list]] = []
        self.started: list[tuple[str, int]] = []
        self.twist_started: list[tuple[str, int]] = []
        self.deck = PromptDeck(
            self.sessions,
            api_get=self.tower.get,
            api_post=self.tower.post,
            download_photo=lambda file_id: (b'JPEGBYTES-' + file_id.encode(), 'image/jpeg'),
            fetch_asset=lambda key: b'ASSET:' + key.encode(),
            send_photo_bytes=lambda c, d, cap: self.sent_photos.append((c, d, cap)),
            send_video_bytes=lambda c, d, cap: self.sent_videos.append((c, d, cap)),
            send_document_bytes=lambda c, d, filename='f.jpg', caption='': self.sent_docs.append((c, d, filename, caption)),
            send_text=lambda c, t: self.texts.append((c, t)),
            send_keyboard=lambda c, t, k: self.keyboards.append((c, t, k)),
            on_render_started=lambda c, r: self.started.append((c, r)),
            on_reverse_started=lambda c, r: self.started.append((c, r)),
            on_twist_started=lambda c, r: self.twist_started.append((c, r)),
        )
        self.key_patches = [
            mock.patch.object(config, 'REPLICATE_API_TOKEN', 'r8_test'),
            mock.patch.object(config, 'OPENAI_API_KEY', 'sk-test'),
            mock.patch.object(config, 'ANTHROPIC_API_KEY', 'sk-ant-test'),
            mock.patch('app.prompts.scan_hold.break_prompt_scan', return_value={'held_s': 900, 'revoked': 0}),
        ]
        for patch in self.key_patches:
            patch.start()

    def tearDown(self):
        for patch in self.key_patches:
            patch.stop()
        self.tmp.cleanup()

    def _pick_model(self, chat: str, engine: str = 'gemini'):
        return self.deck.handle_callback(chat, f'pt:revmodel:{engine}')

    def _skip_twist(self, chat: str):
        return self.deck.handle_callback(chat, 'pt:twistskip')

    def test_list_reply_has_ten_number_buttons_and_flags_outliers(self):
        reply = self.deck.handle_command('1', 'prompts', '')
        self.assertIsInstance(reply, ButtonReply)
        self.assertIn('TOP 10 VIDEO PROMPTS', reply.text)
        self.assertIn('1. 81/100 🔥 — Prompt number 1 · perfume · veo — r/… u/smith', reply.text)
        numbers = [data for row in reply.keyboard[:2] for _label, data in row]
        self.assertEqual(numbers, [f'pt:sel:{i}' for i in range(1, 11)])
        self.assertEqual(reply.keyboard[-1], [('🔄 Scan now', 'pt:scan'), ('📊 Stats', 'pt:stats')])

    def test_list_reply_for_a_past_day_passes_day(self):
        self.deck.handle_command('1', 'prompts', '2026-09-01')
        self.assertEqual(self.tower.gets[0], ('/api/prompts/today', {'day': '2026-09-01'}))

    def test_empty_shortlist_offers_scan_now(self):
        self.tower.prompts = []
        reply = self.deck.list_reply('1')
        self.assertIn('No shortlist', reply.text)
        self.assertEqual(reply.keyboard, [[('🔄 Scan now', 'pt:scan')]])
        self.assertIn('Scan queued', self.deck.handle_callback('1', 'pt:scan').text)
        self.assertEqual(self.tower.posts[-1], ('/api/prompts/scan', {'force': False}))

    def test_detail_shows_scores_reasons_source_and_action_buttons(self):
        reply = self.deck.handle_callback('1', 'pt:sel:3')
        self.assertIn('PROMPT #3 · 83/100', reply.text)
        self.assertIn('Detail 82 · Flow 78 · Structure 90 · baseline 70', reply.text)
        self.assertIn('Hermes: lens stated / clear reveal', reply.text)
        self.assertIn('Source: https://www.reddit.com/r/aivideo/x/', reply.text)
        self.assertEqual(reply.keyboard[0], [('📸 Send product image → video', 'pt:img:3')])
        self.assertEqual([d for _l, d in reply.keyboard[1]], [f'pt:rate:3:{n}' for n in range(1, 6)])
        self.assertEqual(reply.keyboard[2][0], ('📣 Posted on Instagram', 'pt:posted:3'))
        self.assertEqual(self.sessions.get_state('prompt_selected:1'), '3')

    def test_detail_unknown_prompt(self):
        reply = self.deck.handle_callback('1', 'pt:sel:404')
        self.assertEqual(reply.text, 'No prompt #404.')

    def test_photo_before_selection_guides_the_owner(self):
        self.sessions.set_state(STATE_PHOTO.format(chat='1'), 'file-1')
        reply = self.deck.handle_callback('1', 'pt:photo')
        self.assertIn('Pick a prompt first', reply.text)
        self.assertEqual(self.tower.posts, [])

    def test_image_photo_confirm_render_flow(self):
        ask = self.deck.handle_callback('1', 'pt:img:3')
        self.assertIn('Send the product photo now', ask.text)
        self.assertEqual(self.sessions.get_state(STATE_AWAIT_IMAGE.format(chat='1')), '3')
        # Poll loop stashes the photo, then queues the synthetic tap
        self.sessions.set_state(STATE_PHOTO.format(chat='1'), 'file-abc')
        paired = self.deck.handle_callback('1', 'pt:photo')
        self.assertIn('Prompt #3 + your product photo are paired', paired.text)
        self.assertEqual(paired.keyboard, [[('✅ Make video', 'pt:go:3'), ('✖ Cancel', 'pt:cancel')]])
        go = self.deck.handle_callback('1', 'pt:go:3')
        self.assertIn('Rendering prompt #3 (render 77)', go.text)
        path, payload = self.tower.posts[-1]
        self.assertEqual(path, '/api/prompts/3/render')
        self.assertEqual(base64.b64decode(payload['image_base64']), b'JPEGBYTES-file-abc')
        self.assertEqual(payload['chat_id'], '1')
        self.assertEqual(self.started, [('1', 77)])
        # pending state cleared → a second ✅ without a new photo is refused
        self.assertEqual(self.sessions.get_state(STATE_PHOTO.format(chat='1')), '')
        refused = self.deck.handle_callback('1', 'pt:go:3')
        self.assertIn('No product photo on hand', refused.text)

    def test_cancel_clears_pending(self):
        self.deck.handle_callback('1', 'pt:img:3')
        self.sessions.set_state(STATE_PHOTO.format(chat='1'), 'f')
        reply = self.deck.handle_callback('1', 'pt:cancel')
        self.assertIn('Cancelled', reply.text)
        self.assertEqual(self.sessions.get_state(STATE_AWAIT_IMAGE.format(chat='1')), '')

    def test_rate_and_posted(self):
        rated = self.deck.handle_callback('1', 'pt:rate:3:5')
        self.assertIn('⭐5 saved for #3 · now a RAG winner', rated.text)
        self.assertEqual(self.tower.posts[-1], ('/api/prompts/3/rate', {'rating': 5}))
        posted = self.deck.handle_callback('1', 'pt:posted:3')
        self.assertIn('/promptperf 3 likes=', posted.text)

    def test_performance_command_parses_metrics(self):
        reply = self.deck.handle_command('1', 'promptperf', '#3 likes=120 comments: 8 saves=30 views=5400')
        self.assertIn('#3 performance saved — score 31 · now a RAG winner', reply)
        self.assertEqual(
            self.tower.posts[-1],
            ('/api/prompts/3/performance', {'likes': 120, 'comments': 8, 'saves': 30, 'views': 5400}),
        )
        self.assertIn('Usage', self.deck.handle_command('1', 'promptperf', 'likes=3'))

    def test_addprompt_and_stats(self):
        self.assertIn('Usage', self.deck.handle_command('1', 'addprompt', 'too short'))
        added = self.deck.handle_command('1', 'addprompt', 'x' * 80)
        self.assertIn('✅ Added #99 · score 71/100', added.text)
        self.assertEqual(added.keyboard, [[('Open', 'pt:sel:99')]])
        stats = self.deck.handle_command('1', 'promptstats', '')
        self.assertIn('Prompts 40 · scored 38 · pending 2', stats)
        self.assertIn('Baseline (winners) 74 ± 3', stats)
        self.assertIn('Sources: manual 10 · reddit 30', stats)
        self.assertIn('Reels 1 · failed 0 · engine ffmpeg (libx264) at /home/user/anaconda3/envs/ai/bin/ffmpeg', stats)

    def test_stats_names_the_reel_engine_or_the_fix(self):
        self.tower.reel_engine = {'engine': 'pyav', 'ok': True, 'libs': {'av': '14.0.1'}, 'audio': True}
        self.assertIn('engine PyAV 14.0.1 (libx264 + audio)', self.deck.handle_command('1', 'promptstats', ''))
        self.tower.reel_engine = {'engine': 'opencv', 'ok': True, 'libs': {'cv2': '4.10.0'}, 'audio': False}
        self.assertIn('engine OpenCV 4.10.0 (MPEG-4, silent)', self.deck.handle_command('1', 'promptstats', ''))
        self.tower.reel_engine = {
            'engine': 'none', 'ok': False, 'searched': ['/a/ffmpeg', '/b/ffmpeg'], 'rejected': {'/a/ffmpeg': 'no H.264 decoder'},
            'hint': 'no video engine: … Fix: sudo apt install -y ffmpeg',
        }
        stats = self.deck.handle_command('1', 'promptstats', '')
        self.assertIn('⚠️ no video engine — 2 ffmpeg spot(s) checked, av/cv2 absent · fix: sudo apt install -y ffmpeg', stats)
        self.tower.reel_engine = None  # older tower without the field
        self.assertIn('engine unknown', self.deck.handle_command('1', 'promptstats', ''))

    def test_watch_render_sends_card_then_video(self):
        states = iter(['queued', 'running', 'done'])

        def advance(_seconds):
            self.tower.render_status['status'] = next(states)
            if self.tower.render_status['status'] == 'done':
                self.tower.render_status.update({
                    'video_key': 'prompts/d/video.mp4',
                    'video_url': 'https://tower.example/api/partner/v1/assets/prompts/d/video.mp4',
                    'model': 'kwaivgi/kling-v2.1',
                })
        status = self.deck.watch_render('1', 77, poll_s=1, max_wait_s=100, sleep=advance)
        self.assertEqual(status, 'done')
        self.assertEqual(len(self.sent_photos), 1)  # card once, not per poll
        self.assertEqual(self.sent_photos[0][1], b'ASSET:prompts/d/card.png')
        self.assertIn('Preview card', self.sent_photos[0][2])
        # No reel could be composed → the raw clip goes out with the reason
        self.assertEqual(len(self.sent_videos), 1)
        self.assertEqual(self.sent_videos[0][1], b'ASSET:prompts/d/video.mp4')
        self.assertIn('raw clip ready · kwaivgi/kling-v2.1', self.sent_videos[0][2])
        self.assertIn('Reel not composed', self.sent_videos[0][2])

    def test_watch_render_delivers_the_reel_as_the_post_asset(self):
        self.tower.render_status = {
            'id': 79, 'prompt_id': 3, 'status': 'done',
            'video_key': 'prompts/d/video.mp4',
            'video_url': 'https://tower.example/api/partner/v1/assets/prompts/d/video.mp4',
            'reel_key': 'prompts/d/reel.mp4',
            'reel_url': 'https://tower.example/api/partner/v1/assets/prompts/d/reel.mp4',
            'model': 'kwaivgi/kling-v2.1',
        }
        self.assertEqual(self.deck.watch_render('1', 79, poll_s=1, max_wait_s=5, sleep=lambda s: None), 'done')
        self.assertEqual(len(self.sent_videos), 1)
        self.assertEqual(self.sent_videos[0][1], b'ASSET:prompts/d/reel.mp4')
        caption = self.sent_videos[0][2]
        self.assertIn('reel ready, post this', caption)
        self.assertIn(
            'Save clip: https://tower.example/api/partner/v1/assets/prompts/d/video.mp4?download=1',
            caption,
        )
        self.assertEqual(
            self.keyboards[0][2][0][0],
            ('⬇️ Save clip', 'https://tower.example/api/partner/v1/assets/prompts/d/video.mp4?download=1'),
        )
        self.assertEqual(
            self.keyboards[0][2][1][0],
            ('⬇️ Save reel', 'https://tower.example/api/partner/v1/assets/prompts/d/reel.mp4?download=1'),
        )

    def test_watch_render_reports_failure_and_timeout(self):
        self.tower.render_status = {'id': 77, 'prompt_id': 3, 'status': 'failed', 'error': 'model 500'}
        self.assertEqual(self.deck.watch_render('1', 77, poll_s=1, max_wait_s=5, sleep=lambda s: None), 'failed')
        self.assertIn('failed: model 500', self.texts[-1][1])
        self.tower.render_status = {'id': 78, 'prompt_id': 3, 'status': 'running'}
        self.assertEqual(self.deck.watch_render('1', 78, poll_s=2, max_wait_s=4, sleep=lambda s: None), 'timeout')
        self.assertIn('still running', self.texts[-1][1])

    def test_daily_push_once_per_day_and_only_with_a_shortlist(self):
        sent: list[tuple[str, str, list | None]] = []
        self.tower.prompts = []
        self.assertFalse(self.deck.deliver_daily({'1'}, lambda c, t, k: sent.append((c, t, k))))
        self.assertTrue(self.deck.daily_push_due())
        self.tower.prompts = [prompt_row(i) for i in range(1, 11)]
        self.assertTrue(self.deck.deliver_daily({'1', '2'}, lambda c, t, k: sent.append((c, t, k))))
        self.assertEqual(sorted(c for c, _t, _k in sent), ['1', '2'])
        self.assertFalse(self.deck.daily_push_due())
        self.assertFalse(self.deck.deliver_daily({'1'}, lambda c, t, k: sent.append((c, t, k))))
        self.assertEqual(len(sent), 2)

    def test_igtovid_breaks_promptscan(self):
        with mock.patch('app.prompts.scan_hold.break_prompt_scan', return_value={'held_s': 900, 'revoked': 1}) as broke:
            self.deck.handle_command('1', 'igtovid', '')
        broke.assert_called_once()

    def test_igtovid_url_then_title_then_model_starts_reverse(self):
        reply = self.deck.handle_command('1', 'igtovid', '')
        self.assertEqual(reply.text, 'Now Send me the Instagram or Pinterest link.')
        self.assertNotIn('magic-pencil', reply.text.lower())
        self.assertNotIn('cinematic', reply.text.lower())
        self.assertEqual(self.sessions.get_state(STATE_AWAIT_URL.format(chat='1'), ''), '1')
        asked = self.deck.maybe_take_url('1', 'see https://www.instagram.com/reel/AbC123/')
        self.assertIsNotNone(asked)
        self.assertEqual(asked.text, 'Whats the hook?')
        self.assertEqual(self.sessions.get_state(STATE_AWAIT_TITLE.format(chat='1'), ''), '1')
        self.assertEqual(self.started, [])
        model_ask = self.deck.maybe_take_title('1', 'CINEMATIC AI AD')
        self.assertIn('Select a Prompt Model', model_ask.text)
        self.assertEqual([row[0][0] for row in model_ask.keyboard[:3]], ['Gemini', 'GPT-6 Astra', 'Claude Fable 5'])
        self.assertEqual(self.sessions.get_state(STATE_AWAIT_MODEL.format(chat='1'), ''), '1')
        self.assertEqual(self.sessions.get_state(STATE_AWAIT_TWIST.format(chat='1'), ''), '')
        self.assertEqual(self.started, [])
        started = self._pick_model('1', 'gemini')
        self.assertIn('Workflow Started', started.text)
        self.assertEqual(self.started, [('1', 11)])
        self.assertEqual(started.keyboard[0][0], ('🔄 Retry', 'pt:revretry:11'))
        payload = self.tower.posts[-1][1]
        self.assertEqual(payload['source_url'], 'https://www.instagram.com/reel/AbC123/')
        self.assertEqual(payload['title'], 'CINEMATIC AI AD')
        self.assertEqual(payload['vision_engine'], 'gemini')
        self.assertNotIn('twist', payload)
        self.assertEqual(self.sessions.get_state(STATE_AWAIT_TITLE.format(chat='1'), ''), '')
        self.assertEqual(self.sessions.get_state(STATE_AWAIT_MODEL.format(chat='1'), ''), '')
        self.assertEqual(self.sessions.get_state(STATE_LAST_REVERSE.format(chat='1'), ''), '11')

    def test_leftover_intake_twist_does_not_steal_the_hook(self):
        self.deck.handle_command('1', 'igtovid', 'https://www.instagram.com/reel/AbC123/')
        self.sessions.set_state(STATE_AWAIT_TWIST.format(chat='1'), '1')
        stolen = self.deck.maybe_take_twist('1', 'Eiffel tower making step by step assembly')
        self.assertIsNone(stolen)
        asked = self.deck.maybe_take_title('1', 'Eiffel tower making step by step assembly')
        self.assertIn('Select a Prompt Model', asked.text)
        self.assertEqual(self.started, [])

    def test_stale_or_clipless_model_tap_asks_for_the_link(self):
        reply = self._pick_model('1', 'gemini')
        self.assertEqual(reply.text, REVERSE_ASK)
        self.assertEqual(self.tower.posts, [])
        self.sessions.set_state(STATE_AWAIT_MODEL.format(chat='1'), '1')
        reply = self._pick_model('1', 'gemini')
        self.assertEqual(reply.text, REVERSE_ASK)
        self.assertEqual(self.tower.posts, [])

    def test_stale_gemini_with_pending_url_starts_even_without_await_model(self):
        """URL arrived before the hook. Leftover Gemini must not re-ask it."""
        self.sessions.set_state(STATE_PENDING_URL.format(chat='1'), 'https://www.instagram.com/reel/AbC123/')
        self.sessions.set_state(STATE_PENDING_TITLE.format(chat='1'), 'EIFFEL TOWER')
        started = self._pick_model('1', 'gemini')
        self.assertIn('Workflow Started', started.text)
        self.assertEqual(self.tower.posts[-1][1]['source_url'], 'https://www.instagram.com/reel/AbC123/')
        self.assertEqual(self.tower.posts[-1][1]['title'], 'EIFFEL TOWER')
        self.assertEqual(self.sessions.get_state(STATE_LAST_REVERSE.format(chat='1'), ''), '11')

    def test_second_gemini_tap_after_start_resumes_instead_of_reasking(self):
        self.deck.handle_command('1', 'igtovid', 'https://www.instagram.com/reel/AbC123/')
        self.deck.maybe_take_title('1', 'EIFFEL TOWER')
        started = self._pick_model('1', 'gemini')
        self.assertIn('Workflow Started', started.text)
        self.assertEqual(len(self.tower.posts), 1)
        self.assertEqual(self.sessions.get_state(STATE_PENDING_URL.format(chat='1'), ''), '')
        again = self._pick_model('1', 'gemini')
        self.assertIn('Workflow Started', again.text)
        self.assertEqual(len(self.tower.posts), 1)

    def test_old_skip_twist_button_asks_for_the_link(self):
        reply = self.deck.handle_callback('1', 'pt:twistskip')
        self.assertEqual(reply.text, REVERSE_ASK)
        self.assertEqual(self.tower.posts, [])

    def test_astra_button_sends_vision_engine(self):
        self.deck.handle_command('1', 'igtovid', 'https://www.instagram.com/reel/AbC123/')
        self.deck.maybe_take_title('1', 'CINEMATIC AI AD')
        started = self._pick_model('1', 'astra')
        self.assertIn('Workflow Started', started.text)
        self.assertEqual(self.tower.posts[-1][1]['vision_engine'], 'astra')

    def test_missing_openai_key_keeps_model_buttons(self):
        self.deck.handle_command('1', 'igtovid', 'https://www.instagram.com/reel/AbC123/')
        self.deck.maybe_take_title('1', 'CINEMATIC AI AD')
        with mock.patch.object(config, 'OPENAI_API_KEY', ''):
            reply = self._pick_model('1', 'astra')
        self.assertIn('OPENAI_API_KEY', reply.text)
        self.assertEqual(self.started, [])
        self.assertEqual(self.sessions.get_state(STATE_AWAIT_MODEL.format(chat='1'), ''), '1')

    def test_pintovid_with_url_asks_for_title_first(self):
        reply = self.deck.handle_command('1', 'pintovid', 'https://www.pinterest.com/pin/123456/')
        self.assertEqual(reply.text, 'Whats the hook?')
        self.assertEqual(self.started, [])
        model_ask = self.deck.maybe_take_title('1', 'PACIFIC CHILL')
        self.assertIn('Select a Prompt Model', model_ask.text)
        started = self._pick_model('1', 'fable')
        self.assertIn('Workflow Started', started.text)
        self.assertEqual(self.tower.posts[-1][1]['title'], 'PACIFIC CHILL')
        self.assertEqual(self.tower.posts[-1][1]['vision_engine'], 'fable')

    def test_stray_direct_mp4_without_command_is_ignored(self):
        self.assertIsNone(self.deck.maybe_take_url('1', 'https://cdn.example.com/clip.mp4'))
        self.assertEqual(self.tower.posts, [])

    def test_direct_mp4_after_igtovid_asks_for_title(self):
        self.deck.handle_command('1', 'igtovid', '')
        reply = self.deck.maybe_take_url('1', 'https://cdn.example.com/clip.mp4')
        self.assertIsNotNone(reply)
        self.assertEqual(reply.text, 'Whats the hook?')
        self.deck.maybe_take_title('1', 'NIGHT REEL')
        started = self._pick_model('1', 'gemini')
        self.assertIn('Workflow Started', started.text)

    def test_cancel_clears_await_url_and_title(self):
        self.deck.handle_command('1', 'igtovid', '')
        self.deck.handle_callback('1', 'pt:cancel')
        self.assertEqual(self.sessions.get_state(STATE_AWAIT_URL.format(chat='1'), ''), '')
        self.assertIsNone(self.deck.maybe_take_url('1', 'https://cdn.example.com/clip.mp4'))
        self.deck.handle_command('1', 'igtovid', 'https://www.instagram.com/reel/AbC123/')
        self.deck.handle_callback('1', 'pt:cancel')
        self.assertEqual(self.sessions.get_state(STATE_AWAIT_TITLE.format(chat='1'), ''), '')
        self.assertIsNone(self.deck.maybe_take_title('1', 'CINEMATIC AI AD'))
        self.deck.handle_command('1', 'igtovid', 'https://www.instagram.com/reel/AbC123/')
        self.deck.maybe_take_title('1', 'CINEMATIC AI AD')
        self.assertEqual(self.sessions.get_state(STATE_AWAIT_MODEL.format(chat='1'), ''), '1')
        self.deck.handle_callback('1', 'pt:cancel')
        self.assertEqual(self.sessions.get_state(STATE_AWAIT_MODEL.format(chat='1'), ''), '')
        self.deck.handle_command('1', 'igtovid', 'https://www.instagram.com/reel/AbC123/')
        self.deck.maybe_take_title('1', 'CINEMATIC AI AD')
        self.deck.handle_callback('1', 'pt:cancel')
        self.assertEqual(self.sessions.get_state(STATE_AWAIT_MODEL.format(chat='1'), ''), '')
        self.assertIn('link', self.deck.handle_callback('1', 'pt:revmodel:gemini').text.lower())

    def test_forwarded_video_asks_for_title_then_uploads(self):
        self.sessions.set_state(STATE_VIDEO.format(chat='1'), 'vid-9')
        asked = self.deck.handle_callback('1', 'pt:video')
        self.assertEqual(asked.text, 'Whats the hook?')
        self.assertEqual(self.tower.posts, [])
        model_ask = self.deck.maybe_take_title('1', 'ROBE FILM')
        self.assertIn('Select a Prompt Model', model_ask.text)
        started = self._pick_model('1', 'gemini')
        self.assertIn('Workflow Started', started.text)
        payload = self.tower.posts[-1][1]
        self.assertIn('video_base64', payload)
        self.assertEqual(payload['title'], 'ROBE FILM')
        self.assertEqual(base64.b64decode(payload['video_base64']), b'JPEGBYTES-vid-9')
        self.assertEqual(self.sessions.get_state(STATE_VIDEO.format(chat='1'), ''), '')

    def test_watch_reverse_delivers_reel_without_flooding_the_prompt(self):
        long_prompt = '\n'.join(f'[{i}.0s–{i + 1}.0s] shot detail ' + ('x' * 80) for i in range(60))
        self.tower.reverse_status = {
            'id': 11, 'status': 'done', 'keyword': 'COFFEE',
            'prompt_text': long_prompt, 'model': 'google/gemini-2.5-flash',
            'prompt_id': 44, 'reel_key': 'prompts/d/rreel.mp4',
            'video_key': 'prompts/d/src.mp4',
            'video_url': 'https://tower.example/api/partner/v1/assets/prompts/d/src.mp4',
            'ref_frames': [
                {'t': 0.0, 'key': 'prompts/d/rref-01.jpg', 'filename': 'cut-01-0.00s.jpg'},
                {'t': 1.76, 'key': 'prompts/d/rref-02.jpg', 'filename': 'cut-02-1.76s.jpg'},
            ],
            'timings': {'started_at': '2026-09-12T14:00:00+00:00', 'total': 121, 'download': 18, 'describe': 70, 'reel': 8},
        }
        self.assertEqual(self.deck.watch_reverse('1', 11, poll_s=1, max_wait_s=5, sleep=lambda s: None), 'done')
        self.assertEqual(len(self.sent_videos), 2)
        self.assertEqual(self.sent_videos[0][1], b'ASSET:prompts/d/src.mp4')
        self.assertIn('original clip', self.sent_videos[0][2])
        self.assertIn('Tap the video to save', self.sent_videos[0][2])
        self.assertEqual(self.sent_videos[1][1], b'ASSET:prompts/d/rreel.mp4')
        self.assertIn('reel ready, post this', self.sent_videos[1][2])
        self.assertEqual(self.sent_docs, [])
        self.assertTrue(any(t.startswith('⏱ ') and 'download' in t for _c, t in self.texts))
        self.assertEqual(self.keyboards[0][1], 'Shall we twist the video?')
        keyboard = self.keyboards[0][2]
        self.assertEqual(
            keyboard[0][0],
            ('⬇️ Save clip', 'https://tower.example/api/partner/v1/assets/prompts/d/src.mp4?download=1'),
        )
        self.assertEqual(keyboard[-3], [('🖼 Images', 'pt:imgs:11')])
        self.assertEqual(keyboard[-2], [('Show prompt', 'pt:show:11'), ('Copy prompt', 'pt:copy:11')])
        self.assertEqual(keyboard[-1], [('💥 Twist', 'pt:twist:11')])
        self.assertFalse(any('📝 Prompt #11' in t for _c, t in self.texts))
        self.assertFalse(any(long_prompt.split('\n', 1)[0] in t for _c, t in self.texts))
        shown = self.deck.handle_callback('1', 'pt:show:11')
        self.assertTrue(shown.text.startswith('📝 Prompt #11'))
        self.assertIn(long_prompt.split('\n', 1)[0], shown.text)
        copied = self.deck.handle_callback('1', 'pt:copy:11')
        self.assertEqual(copied.text, 'Prompt file sent — open it to copy.')
        self.assertEqual(self.sent_docs[-1][2], 'prompt-11.txt')

    def test_images_button_sends_four_then_asks_for_more(self):
        self.tower.reverse_status = {
            'id': 12, 'status': 'done', 'keyword': 'JUICE',
            'prompt_text': '[0.0s–8.0s] a drink.',
            'ref_frames': [
                {'t': float(i), 'key': f'prompts/d/rref-{i:02d}.jpg', 'filename': f'cut-{i + 1:02d}-{i:.2f}s.jpg'}
                for i in range(6)
            ],
        }
        with mock.patch('app.telegram_prompts.time.sleep'):
            first = self.deck.handle_callback('1', 'pt:imgs:12')
        self.assertEqual(len(self.sent_docs), 4)
        self.assertEqual([doc[2] for doc in self.sent_docs], [
            'cut-01-0.00s.jpg', 'cut-02-1.00s.jpg', 'cut-03-2.00s.jpg', 'cut-04-3.00s.jpg',
        ])
        self.assertIn('1–4 of 6', first.text)
        self.assertEqual(first.keyboard[0][0], ('More images ▸', 'pt:imgs:12:4'))
        more = self.deck.images_reply('1', 12, offset=4, sleep=lambda s: None)
        self.assertEqual(len(self.sent_docs), 6)
        self.assertIn('5–6 of 6', more.text)
        self.assertFalse(more.keyboard)

    def test_images_retries_flood_on_a_page(self):
        hits: dict[str, int] = {}

        def send(c, d, filename='f.jpg', caption=''):
            hits[filename] = hits.get(filename, 0) + 1
            if filename == 'cut-01-0.00s.jpg' and hits[filename] == 1:
                raise RuntimeError('Too Many Requests: retry after 1')
            self.sent_docs.append((c, d, filename, caption))

        self.deck.send_document_bytes = send
        self.tower.reverse_status = {
            'id': 12, 'status': 'done',
            'ref_frames': [
                {'t': float(i), 'key': f'prompts/d/rref-{i:02d}.jpg', 'filename': f'cut-{i + 1:02d}-{i:.2f}s.jpg'}
                for i in range(6)
            ],
        }
        reply = self.deck.images_reply('1', 12, sleep=lambda s: None)
        self.assertEqual(len(self.sent_docs), 4)
        self.assertEqual(hits['cut-01-0.00s.jpg'], 2)
        self.assertIn('More images', reply.text)

    def test_images_says_when_a_frame_is_missing(self):
        def fetch(key: str) -> bytes:
            if key.endswith('01.jpg'):
                raise RuntimeError('missing asset')
            return b'ASSET:' + key.encode()

        self.deck.fetch_asset = fetch
        self.tower.reverse_status = {
            'id': 12, 'status': 'done',
            'ref_frames': [
                {'t': float(i), 'key': f'prompts/d/rref-{i:02d}.jpg', 'filename': f'cut-{i + 1:02d}-{i:.2f}s.jpg'}
                for i in range(6)
            ],
        }
        reply = self.deck.images_reply('1', 12, sleep=lambda s: None)
        self.assertEqual(len(self.sent_docs), 3)
        self.assertIn('1 missed (2)', reply.text)
        self.assertIn('More images', reply.text)

    def test_watch_reverse_announces_describing_then_reel_failure_keeps_clip(self):
        states = iter([
            {'id': 11, 'status': 'describing', 'duration_s': 8.2, 'vision_engine': 'astra'},
            {
                'id': 11, 'status': 'done', 'keyword': 'WATCH',
                'prompt_text': '[0.0s–8.0s] a hero watch on wet slate.',
                'video_key': 'prompts/d/src.mp4', 'reel_key': None,
                'reel_error': 'no video engine',
            },
        ])
        self.tower.get = lambda path, params=None: next(states)
        self.deck.api_get = self.tower.get
        self.assertEqual(self.deck.watch_reverse('1', 11, poll_s=1, max_wait_s=5, sleep=lambda s: None), 'done')
        self.assertIn('Workflow Started', self.texts[0][1])
        self.assertIn('Reel not composed: no video engine', self.sent_videos[0][2])
        self.assertEqual(self.sent_videos[0][1], b'ASSET:prompts/d/src.mp4')

    def test_watch_reverse_heartbeats_while_gemini_is_watching(self):
        self.deck.api_get = lambda path, params=None: {
            'id': 16, 'status': 'describing', 'duration_s': 25.0, 'vision_engine': 'gemini',
        }
        self.assertEqual(
            self.deck.watch_reverse('1', 16, poll_s=45, max_wait_s=100, sleep=lambda s: None),
            'timeout',
        )
        watching = [t for _c, t in self.texts if 'watching' in t.lower()]
        self.assertTrue(any('Workflow Started' in t for _c, t in self.texts))
        self.assertTrue(any('still watching' in t.lower() for t in watching))

    def test_watch_reverse_rewrites_e001_as_gemini_not_video_model(self):
        self.deck.api_get = lambda path, params=None: {
            'id': 16, 'status': 'failed',
            'error': (
                'video model failed: Prediction failed: Async prediction failed: '
                'ModelError: An error occurred while processing your request (E001) (1cah9wlWR99)'
            ),
        }
        self.assertEqual(self.deck.watch_reverse('1', 16, poll_s=1, max_wait_s=5, sleep=lambda s: None), 'failed')
        self.assertIn('Gemini could not read this clip (E001)', self.texts[0][1])
        self.assertNotIn('video model failed', self.texts[0][1])

    def test_watch_reverse_announces_queued_and_kicks_again(self):
        posts: list[str] = []

        def get(path, params=None):
            return {'id': 14, 'status': 'queued'}

        def post(path, payload=None):
            posts.append(path)
            return {'id': 14, 'status': 'queued'}

        self.deck.api_get = get
        self.deck.api_post = post
        self.assertEqual(
            self.deck.watch_reverse('1', 14, poll_s=15, max_wait_s=50, sleep=lambda s: None),
            'timeout',
        )
        self.assertTrue(any(t == 'processing..' for _c, t in self.texts))
        self.assertTrue(any('kicked it again' in t for _c, t in self.texts))
        self.assertTrue(any(p.endswith('/14/retry') for p in posts))

    def test_watch_reverse_says_when_the_queue_is_dead(self):
        self.deck.api_get = lambda path, params=None: {'id': 14, 'status': 'queued'}
        self.deck.api_post = lambda path, payload=None: {'id': 14, 'status': 'queued'}
        self.assertEqual(
            self.deck.watch_reverse('1', 14, poll_s=45, max_wait_s=100, sleep=lambda s: None),
            'timeout',
        )
        self.assertTrue(any('still queued' in t for _c, t in self.texts))
        self.assertTrue(any('link again' in t for _c, t in self.texts))

    def test_retry_button_kicks_stuck_reverse(self):
        self.tower.reverse_status = {'id': 14, 'status': 'queued', 'prompt_text': None}
        reply = self.deck.handle_callback('1', 'pt:revretry:14')
        self.assertIn('kicked again', reply.text.lower())
        self.assertEqual(self.tower.posts[-1][0], '/api/prompts/reverse/14/retry')
        self.assertIn(('1', 14), self.started)

    def test_twist_button_uses_stored_line(self):
        self.tower.reverse_status = {
            'id': 11, 'status': 'done',
            'prompt_text': '[0.0s–8.0s] a juice glass.',
            'twist_text': 'liquid gold temple',
            'ref_frames': [{'t': 0.0, 'key': 'k', 'filename': 'cut-01-0.00s.jpg'}],
        }
        reply = self.deck.handle_callback('1', 'pt:twist:11')
        self.assertIn('Twist #11 started', reply.text)
        self.assertEqual(self.twist_started, [('1', 11)])
        self.assertEqual(self.tower.posts[-1][0], '/api/prompts/reverse/11/twist')
        self.assertEqual(self.tower.posts[-1][1]['twist'], 'liquid gold temple')

    def test_twist_button_asks_when_no_line(self):
        self.tower.reverse_status = {
            'id': 11, 'status': 'done', 'prompt_text': '[0.0s–8.0s] a juice glass.',
        }
        reply = self.deck.handle_callback('1', 'pt:twist:11')
        self.assertEqual(reply.text, 'Shall we twist the video?')
        self.assertEqual(self.sessions.get_state(STATE_AWAIT_TWIST_APPLY.format(chat='1'), ''), '11')
        started = self.deck.maybe_take_twist('1', 'rain of rose petals on the bottle')
        self.assertIn('Twist #11 started', started.text)
        self.assertEqual(self.tower.posts[-1][1]['twist'], 'rain of rose petals on the bottle')

    def test_watch_twist_delivers_prompt_and_frames(self):
        self.tower.reverse_status = {
            'id': 11, 'status': 'done',
            'twist_status': 'done',
            'twist_text': 'liquid gold',
            'twist_keyword': 'GOLD',
            'twist_prompt': '[0.0s–8.0s] liquid gold pours from a temple spout. ' * 4,
            'twist_frames': [
                {'t': 0.0, 'key': 'prompts/d/twref-01.jpg', 'filename': 'twist-01-0.00s.jpg'},
            ],
            'twist_video_key': 'prompts/d/twvid.mp4',
            'twist_video_url': 'https://tower.example/api/partner/v1/assets/prompts/d/twvid.mp4',
        }
        self.assertEqual(self.deck.watch_twist('1', 11, poll_s=1, max_wait_s=5, sleep=lambda s: None), 'done')
        self.assertTrue(any('Twist #11 ready' in t for _c, t in self.texts))
        self.assertTrue(any('liquid gold' in t for _c, t in self.texts))
        self.assertFalse(any('[0.0s–8.0s] liquid gold pours' in t for _c, t in self.texts))
        self.assertEqual(self.sent_videos[-1][1], b'ASSET:prompts/d/twvid.mp4')
        self.assertIn('Gemini Omni', self.sent_videos[-1][2])
        self.assertIn('Tap the video to save', self.sent_videos[-1][2])
        self.assertEqual(self.keyboards[-1][1], 'Prompt ready.')
        self.assertEqual(
            self.keyboards[-1][2][-1],
            [('Show prompt', 'pt:show:11'), ('Copy prompt', 'pt:copy:11')],
        )
        shown = self.deck.handle_callback('1', 'pt:show:11')
        self.assertIn('liquid gold pours', shown.text)
        self.assertEqual(self.sent_docs, [])
        self.assertEqual(self.keyboards[-1][2][-2], [('🖼 Images', 'pt:timgs:11')])
        frames = self.deck.images_reply('1', 11, kind='twist', sleep=lambda s: None)
        self.assertEqual(self.sent_docs[0][2], 'twist-01-0.00s.jpg')
        self.assertIn('1–1 of 1', frames.text)

    def test_watch_twist_failed_offers_retry(self):
        self.tower.reverse_status = {
            'id': 26, 'status': 'done',
            'twist_status': 'failed',
            'twist_error': 'Gemini could not rewrite the prompt with that twist',
        }
        self.assertEqual(self.deck.watch_twist('1', 26, poll_s=1, max_wait_s=5, sleep=lambda s: None), 'failed')
        self.assertEqual(self.keyboards[-1][1], '❌ Twist #26 failed: Gemini could not rewrite the prompt with that twist')
        self.assertEqual(self.keyboards[-1][2][0], [('🔄 Retry twist', 'pt:twist:26')])


class BotWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = TelegramSessionStore(Path(self.tmp.name) / 's.db')
        self.api = FakeTelegramAPI()
        self.engine = FakeEngine()
        self.tower = FakeTower()
        self.engine.api_get = self.tower.get
        self.bot = JobMasterTelegramBot(
            self.api,
            engine=self.engine,
            sessions=self.sessions,
            health_enabled=False,
            owner_chat_ids={'100'},
            tower_post=self.tower.post,
        )
        self.bot.deck.on_render_started = lambda c, r: None
        self.key_patches = [
            mock.patch.object(config, 'REPLICATE_API_TOKEN', 'r8_test'),
            mock.patch.object(config, 'OPENAI_API_KEY', 'sk-test'),
            mock.patch.object(config, 'ANTHROPIC_API_KEY', 'sk-ant-test'),
            mock.patch('app.prompts.scan_hold.break_prompt_scan', return_value={'held_s': 900, 'revoked': 0}),
        ]
        for patch in self.key_patches:
            patch.start()

    def tearDown(self):
        for patch in self.key_patches:
            patch.stop()
        self.tmp.cleanup()

    def test_owner_prompts_command_routes_to_deck(self):
        self.bot._process_locked('100', '/prompts')
        chat, text, keyboard = self.api.keyboards_sent[-1]
        self.assertEqual(chat, '100')
        self.assertIn('TOP 10 VIDEO PROMPTS', text)
        self.assertEqual(len(keyboard), 3)

    def test_guest_cannot_use_prompt_commands_or_taps(self):
        self.bot._process_locked('555', '/prompts')
        self.assertFalse(any('TOP 10' in text for _c, text in self.api.sent))
        self.bot._process_locked('555', f'{BTN_PREFIX}pt:sel:3')
        self.assertFalse(any('PROMPT #3' in text for _c, text in self.api.sent))
        self.assertEqual([p for p, _ in self.tower.gets if p.startswith('/api/prompts/3')], [])

    def test_owner_photo_event_pairs_with_selected_prompt(self):
        self.bot._process_locked('100', f'{BTN_PREFIX}pt:img:3')
        self.sessions.set_state(STATE_PHOTO.format(chat='100'), 'file-9')
        self.bot._process_locked('100', PROMPT_PHOTO_TAP)
        _chat, text, keyboard = self.api.keyboards_sent[-1]
        self.assertIn('Prompt #3 + your product photo are paired', text)
        self.assertEqual(keyboard[0][0], ('✅ Make video', 'pt:go:3'))

    def test_help_lists_prompt_tower_first(self):
        text = self.bot._owner_help()
        self.assertIn('PROMPT TOWER', text)
        self.assertNotIn('/topfreshers', text)
        self.assertIn('/promptperf', text)
        self.assertIn('/igtovid', text)
        self.assertIn('/pintovid', text)

    def test_reverse_intake_is_not_queued_behind_prompt_scan(self):
        """/igtovid must answer on the poll thread — not wait for Ollama."""
        self.assertTrue(REVERSE_INTAKE_COMMANDS)
        self.assertFalse(REVERSE_INTAKE_COMMANDS & PROMPT_COMMANDS)
        self.assertIn('igtovid', REVERSE_INTAKE_COMMANDS)
        self.assertIn('promptscan', PROMPT_COMMANDS)

    def test_owner_igtovid_asks_for_url_then_title_starts_reverse(self):
        self.bot._process_locked('100', '/igtovid')
        _chat, text, keyboard = self.api.keyboards_sent[-1]
        self.assertEqual(text, 'Now Send me the Instagram or Pinterest link.')
        self.assertNotIn('Gemini', text)
        self.assertNotIn('cinematic', text.lower())
        self.assertEqual(keyboard, [[('✖ Cancel', 'pt:cancel')]])
        self.bot._process_locked('100', 'https://www.instagram.com/reel/AbC123xyz/')
        self.assertEqual(self.api.keyboards_sent[-1][1], 'Whats the hook?')
        self.bot._process_locked('100', 'CINEMATIC AI AD')
        self.assertIn('Select a Prompt Model', self.api.keyboards_sent[-1][1])
        self.bot._process_locked('100', f'{BTN_PREFIX}pt:revmodel:gemini')
        self.assertIn('Workflow Started', self.api.keyboards_sent[-1][1])
        self.assertEqual(self.tower.posts[-1][0], '/api/prompts/reverse')
        self.assertEqual(self.tower.posts[-1][1]['title'], 'CINEMATIC AI AD')
        self.assertEqual(self.tower.posts[-1][1]['vision_engine'], 'gemini')
        self.assertNotIn('twist', self.tower.posts[-1][1])

    def test_guest_can_start_reverse_from_command_or_url(self):
        self.bot._process_locked('555', '/igtovid')
        self.assertEqual(self.api.sent[-1][1], 'Now Send me the Instagram or Pinterest link.')
        self.bot._process_locked('555', 'https://www.instagram.com/reel/AbC123xyz/')
        self.assertEqual(self.api.sent[-1][1], 'Whats the hook?')

    def test_owner_video_tap_asks_for_title_then_uploads(self):
        self.sessions.set_state(STATE_VIDEO.format(chat='100'), 'tg-vid')
        self.bot._process_locked('100', PROMPT_VIDEO_TAP)
        self.assertEqual(self.api.keyboards_sent[-1][1], 'Whats the hook?')
        self.bot._process_locked('100', 'ROBE FILM')
        self.assertIn('Select a Prompt Model', self.api.keyboards_sent[-1][1])
        self.bot._process_locked('100', f'{BTN_PREFIX}pt:revmodel:gemini')
        self.assertIn('Workflow Started', self.api.keyboards_sent[-1][1])
        self.assertIn('video_base64', self.tower.posts[-1][1])
        self.assertEqual(self.tower.posts[-1][1]['title'], 'ROBE FILM')

    def test_resume_open_watches_reattaches_unfinished_reverses(self):
        self.tower.reverses = [
            {'id': 21, 'chat_id': '100', 'status': 'queued'},
            {'id': 22, 'chat_id': '100', 'status': 'done', 'twist_status': 'running'},
            {'id': 23, 'status': 'queued'},
        ]
        started: list[tuple[str, int]] = []
        twisted: list[tuple[str, int]] = []
        self.bot._start_reverse_watch = lambda c, r: started.append((c, r))
        self.bot._start_twist_watch = lambda c, r: twisted.append((c, r))
        self.assertEqual(self.bot.resume_open_watches(), 2)
        self.assertEqual(started, [('100', 21)])
        self.assertEqual(twisted, [('100', 22)])

    def test_normalize_update_keeps_photo_file_id(self):
        update = {'message': {'chat': {'id': 100, 'type': 'private'}, 'from': {'username': 'ashok'},
                              'photo': [{'file_id': 'small'}, {'file_id': 'big'}]}}
        is_cb, chat, _sender, text, _cb, file_id = self.bot._normalize_update(update)
        self.assertFalse(is_cb)
        self.assertIsNone(text)
        self.assertEqual(file_id, 'big')

    def test_document_content_type_matches_the_filename(self):
        from scripts.telegram_job_bot import document_content_type

        self.assertEqual(document_content_type('frames-11.zip'), 'application/zip')
        self.assertEqual(document_content_type('prompt-11.txt'), 'text/plain')
        self.assertEqual(document_content_type('cut-01.jpg'), 'image/jpeg')


if __name__ == '__main__':
    unittest.main()
