"""Prompt Tower on Telegram: /prompts deck, select → 📸 → ✅ make video,
⭐ rating, /promptperf, render watcher delivery, once-a-day push, and the
owner-only wiring inside scripts/telegram_job_bot.py."""

from __future__ import annotations

import base64
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from app.telegram_buttons import BTN_PREFIX, ButtonReply
from app.telegram_prompts import PromptDeck, STATE_AWAIT_IMAGE, STATE_PHOTO
from app.telegram_sessions import TelegramSessionStore
from scripts.telegram_job_bot import PROMPT_PHOTO_TAP, JobMasterTelegramBot
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

    def get(self, path: str, params: dict | None = None):
        self.gets.append((path, params))
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
        raise AssertionError(path)


class DeckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = TelegramSessionStore(Path(self.tmp.name) / 's.db')
        self.tower = FakeTower()
        self.sent_photos: list[tuple[str, bytes, str]] = []
        self.sent_videos: list[tuple[str, bytes, str]] = []
        self.texts: list[tuple[str, str]] = []
        self.started: list[tuple[str, int]] = []
        self.deck = PromptDeck(
            self.sessions,
            api_get=self.tower.get,
            api_post=self.tower.post,
            download_photo=lambda file_id: (b'JPEGBYTES-' + file_id.encode(), 'image/jpeg'),
            fetch_asset=lambda key: b'ASSET:' + key.encode(),
            send_photo_bytes=lambda c, d, cap: self.sent_photos.append((c, d, cap)),
            send_video_bytes=lambda c, d, cap: self.sent_videos.append((c, d, cap)),
            send_text=lambda c, t: self.texts.append((c, t)),
            on_render_started=lambda c, r: self.started.append((c, r)),
        )

    def tearDown(self):
        self.tmp.cleanup()

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
        self.assertIn('Raw clip: https://tower.example/api/partner/v1/assets/prompts/d/video.mp4', caption)

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

    def tearDown(self):
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
        self.assertLess(text.index('Prompt Tower'), text.index('/topfreshers'))
        self.assertIn('/promptperf', text)

    def test_normalize_update_keeps_photo_file_id(self):
        update = {'message': {'chat': {'id': 100, 'type': 'private'}, 'from': {'username': 'ashok'},
                              'photo': [{'file_id': 'small'}, {'file_id': 'big'}]}}
        is_cb, chat, _sender, text, _cb, file_id = self.bot._normalize_update(update)
        self.assertFalse(is_cb)
        self.assertIsNone(text)
        self.assertEqual(file_id, 'big')


if __name__ == '__main__':
    unittest.main()
