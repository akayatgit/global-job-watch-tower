"""Reverse prompt: Instagram / Pinterest URL → clip → Gemini → reel."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.api import prompts as prompts_api
from app.db import Base, get_db
from app.models import ReversePrompt
from app.prompts import reverse_prompt
from app.prompts.reverse_prompt import ReverseError, ReverseReading


FAKE_MP4 = b'\x00\x00\x00\x18ftypisom' + b'\x00' * 60_000
IG_URL = 'https://www.instagram.com/reel/AbC123xyz/?igsh=tracker'
PIN_URL = 'https://www.pinterest.com/pin/987654321/'
OG_HTML = (
    '<html><head>'
    '<meta property="og:video" content="https://cdn.example.com/clip.mp4">'
    '<meta property="og:video:secure_url" content="https://cdn.example.com/hd.mp4">'
    '</head></html>'
)


def make_session():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def make_client(db):
    app = FastAPI()
    app.include_router(prompts_api.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


class UrlAndParseTests(unittest.TestCase):
    def test_detect_platform(self):
        self.assertEqual(reverse_prompt.detect_platform(IG_URL), 'instagram')
        self.assertEqual(reverse_prompt.detect_platform('https://instagram.com/p/AbC123/'), 'instagram')
        self.assertEqual(reverse_prompt.detect_platform('https://www.instagram.com/shop/reel/AbC123/'), 'instagram')
        self.assertEqual(reverse_prompt.detect_platform(PIN_URL), 'pinterest')
        self.assertEqual(reverse_prompt.detect_platform('https://pin.it/abcDEF'), 'pinterest')
        self.assertEqual(reverse_prompt.detect_platform('https://cdn.example.com/a.mp4'), 'direct')
        self.assertEqual(reverse_prompt.detect_platform('https://cdn.example.com/a.m3u8?x=1'), 'direct')
        self.assertIsNone(reverse_prompt.detect_platform('https://youtube.com/watch?v=abc'))
        self.assertIsNone(reverse_prompt.detect_platform('not a url'))

    def test_canonical_url_strips_instagram_tracking(self):
        self.assertEqual(
            reverse_prompt.canonical_url(IG_URL),
            'https://www.instagram.com/reel/AbC123xyz/',
        )
        self.assertEqual(reverse_prompt.canonical_url(PIN_URL), PIN_URL)

    def test_find_url_in_prose(self):
        self.assertEqual(
            reverse_prompt.find_url('see this ' + IG_URL + ' please'),
            IG_URL,
        )

    def test_extract_media_urls_prefers_mp4_over_hls(self):
        html = (
            OG_HTML
            + '"V_HLSV3": {"url": "https://cdn.example.com/master.m3u8"}'
            + r' "playable_url": "https:\/\/cdn.example.com\/escaped.mp4"'
        )
        urls = reverse_prompt.extract_media_urls(html)
        self.assertTrue(urls)
        self.assertTrue(any(u.endswith('.mp4') for u in urls))
        self.assertLess(
            next(i for i, u in enumerate(urls) if u.endswith('.mp4')),
            next(i for i, u in enumerate(urls) if '.m3u8' in u),
        )
        self.assertIn('https://cdn.example.com/escaped.mp4', urls)

    def test_clean_keyword_and_parse_reading(self):
        self.assertEqual(reverse_prompt.clean_keyword('coffee dripper!!'), 'COFFEE')
        self.assertEqual(reverse_prompt.clean_keyword(''), 'PRODUCT')
        reading = reverse_prompt.parse_reading(
            '```json\n{"keyword": "skincare", "prompt": "[0.0s–1.0s] a serum bottle.\\n"}\n```',
            model='google/gemini-2.5-flash',
        )
        self.assertEqual(reading.keyword, 'SKINCARE')
        self.assertIn('serum bottle', reading.prompt)
        wrapped = reverse_prompt.parse_reading(
            'Sure.\n{"keyword": "WATCH", "prompt": "[0.0s–2.0s] a watch on slate."}\nThanks.',
        )
        self.assertEqual(wrapped.keyword, 'WATCH')
        bare = reverse_prompt.parse_reading('[0.0s–8.0s] ' + ('a cinematic product shot. ' * 10))
        self.assertEqual(bare.keyword, 'PRODUCT')
        with self.assertRaises(ReverseError):
            reverse_prompt.parse_reading('nope')

    def test_build_instruction_carries_every_dimension_and_the_exemplar(self):
        text = reverse_prompt.build_instruction(duration_s=8.0, exemplar='EXEMPLAR BODY')
        self.assertIn('8.0-second', text)
        for dimension in reverse_prompt.DIMENSIONS:
            self.assertIn(dimension.split('(')[0].strip(), text)
        self.assertIn('EXEMPLAR BODY', text)
        self.assertIn('"keyword"', text)
        bundled = reverse_prompt.load_exemplar()
        self.assertIn('coffee dripper', bundled.lower())


class FetchAndDescribeTests(unittest.TestCase):
    def test_fetch_video_from_og_meta(self):
        def http_fetch(url, referer=None, max_bytes=None):
            if 'instagram.com' in url:
                return OG_HTML.encode()
            if url.endswith('.mp4'):
                return FAKE_MP4
            raise AssertionError(url)

        fetched = reverse_prompt.fetch_video(IG_URL, http_fetch=http_fetch, ffmpeg=None)
        self.assertEqual(fetched.platform, 'instagram')
        self.assertEqual(fetched.data, FAKE_MP4)
        self.assertTrue(fetched.media_url.endswith('.mp4'))

    def test_fetch_video_falls_back_to_browser_on_login_wall(self):
        def http_fetch(url, referer=None, max_bytes=None):
            if 'instagram.com' in url:
                raise reverse_prompt.urllib.error.HTTPError(url, 401, 'login', {}, None)
            if url.endswith('.mp4'):
                return FAKE_MP4
            raise AssertionError(url)

        fetched = reverse_prompt.fetch_video(
            IG_URL,
            http_fetch=http_fetch,
            browser_fetch=lambda url: OG_HTML,
            ffmpeg=None,
        )
        self.assertEqual(fetched.platform, 'instagram')
        self.assertEqual(fetched.data, FAKE_MP4)

    def test_fetch_video_rejects_unknown_hosts_and_hls_without_ffmpeg(self):
        with self.assertRaises(ReverseError):
            reverse_prompt.fetch_video('https://youtube.com/watch?v=abc')

        def http_fetch(url, referer=None, max_bytes=None):
            if 'pinterest' in url:
                return b'<html>"V_HLSV3": {"url": "https://v.pinimg.com/a.m3u8"}</html>'
            raise AssertionError(url)

        with self.assertRaises(ReverseError) as ctx:
            reverse_prompt.fetch_video(PIN_URL, http_fetch=http_fetch, ffmpeg=None)
        self.assertIn('HLS', str(ctx.exception))

    def test_fetch_direct_mp4(self):
        fetched = reverse_prompt.fetch_video(
            'https://cdn.example.com/a.mp4',
            http_fetch=lambda url, referer=None, max_bytes=None: FAKE_MP4,
        )
        self.assertEqual(fetched.platform, 'direct')
        self.assertEqual(fetched.data, FAKE_MP4)

    def test_describe_video_uses_injected_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'clip.mp4'
            path.write_bytes(FAKE_MP4)
            seen: dict = {}

            def run(model, input):
                seen['model'] = model
                seen['keys'] = sorted(input)
                seen['prompt'] = input['prompt']
                handle = input['videos'][0]
                self.assertTrue(hasattr(handle, 'read'))
                return json.dumps({
                    'keyword': 'COFFEE',
                    'prompt': '[0.0s–8.0s] a ceramic dripper under morning light.',
                })

            reading = reverse_prompt.describe_video(
                path, duration_s=8.0, run=run, exemplar='BAR',
            )
            self.assertEqual(reading.keyword, 'COFFEE')
            self.assertIn('dripper', reading.prompt)
            self.assertEqual(seen['model'], config.REPLICATE_VISION_MODEL)
            self.assertIn('system_instruction', seen['keys'])
            self.assertIn('8.0-second', seen['prompt'])


class ReverseApiAndTaskTests(unittest.TestCase):
    def setUp(self):
        self.db = make_session()
        self.client = make_client(self.db)
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(config, 'PARTNER_ASSETS_DIR', self.tmp.name),
            mock.patch.object(config, 'PARTNER_PUBLIC_BASE_URL', 'https://tower.example'),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def test_post_url_queues_and_get_returns_the_row(self):
        with mock.patch('app.tasks.reverse_prompt_video') as queued:
            response = self.client.post(
                '/api/prompts/reverse',
                json={'source_url': IG_URL, 'chat_id': '100'},
            )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body['status'], 'queued')
        self.assertEqual(body['platform'], 'instagram')
        self.assertEqual(body['source_url'], 'https://www.instagram.com/reel/AbC123xyz/')
        queued.delay.assert_called_once_with(body['id'])
        listed = self.client.get('/api/prompts/reverse').json()
        self.assertEqual(listed['total'], 1)
        self.assertEqual(self.client.get(f"/api/prompts/reverse/{body['id']}").json()['id'], body['id'])

    def test_post_rejects_unknown_url(self):
        response = self.client.post('/api/prompts/reverse', json={'source_url': 'https://youtube.com/x'})
        self.assertEqual(response.status_code, 422)

    def test_post_base64_stores_the_clip(self):
        with mock.patch('app.tasks.reverse_prompt_video') as queued:
            response = self.client.post(
                '/api/prompts/reverse',
                json={'video_base64': base64.b64encode(FAKE_MP4).decode('ascii'), 'chat_id': '100'},
            )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body['platform'], 'upload')
        self.assertTrue(body['video_key'])
        self.assertTrue((Path(self.tmp.name) / body['video_key']).is_file())
        queued.delay.assert_called_once()

    def test_post_rejects_non_video_bytes(self):
        junk = base64.b64encode(b'not-a-video').decode('ascii')
        self.assertEqual(
            self.client.post('/api/prompts/reverse', json={'video_base64': junk}).status_code,
            422,
        )

    def test_task_happy_path_writes_prompt_and_reel(self):
        from app import tasks
        from app.prompts.video_creator import ReelAsset

        with mock.patch('app.tasks.reverse_prompt_video') as queued:
            reverse_id = self.client.post(
                '/api/prompts/reverse', json={'source_url': IG_URL},
            ).json()['id']
        queued.delay.assert_called_once()

        class _SessionCtx:
            def __init__(self, db):
                self.db = db

            def __enter__(self):
                return self.db

            def __exit__(self, *exc):
                return False

        fetched = reverse_prompt.FetchedVideo(data=FAKE_MP4, media_url='https://cdn.example.com/c.mp4', platform='instagram')
        reading = ReverseReading(
            keyword='COFFEE',
            prompt='[0.0s–8.0s] a ceramic dripper under morning light. ' * 8,
            model='google/gemini-2.5-flash',
            raw='{}',
        )
        reel = ReelAsset(
            reel_key='prompts/d/rreel-1.mp4',
            reel_path=Path(self.tmp.name) / 'prompts/d/rreel-1.mp4',
            reel_url='https://tower.example/api/partner/v1/assets/prompts/d/rreel-1.mp4',
            frames=6, duration_s=8.0, engine='ffmpeg',
        )
        with mock.patch.object(tasks, 'SessionLocal', lambda: _SessionCtx(self.db)), \
                mock.patch('app.prompts.reverse_prompt.fetch_video', return_value=fetched), \
                mock.patch('app.prompts.reverse_prompt.describe_video', return_value=reading), \
                mock.patch('app.prompts.video_creator.create_reel', return_value=reel), \
                mock.patch('app.prompts.post_reel.probe', return_value=mock.Mock(duration_s=8.0)), \
                mock.patch('app.prompts.post_reel.resolve_engine', return_value=(mock.Mock(exe='/usr/bin/ffmpeg'), {})), \
                mock.patch('app.prompts.pipeline.ingest', return_value=(None, 'rejected')), \
                mock.patch('app.tasks.console_log'):
            result = tasks.reverse_prompt_video.run(reverse_id)
        self.assertTrue(result['ok'], result)
        row = self.db.get(ReversePrompt, reverse_id)
        self.assertEqual(row.status, 'done')
        self.assertEqual(row.keyword, 'COFFEE')
        self.assertIn('dripper', row.prompt_text)
        self.assertEqual(row.reel_key, 'prompts/d/rreel-1.mp4')
        self.assertTrue(row.video_key)

    def test_task_reel_failure_still_finishes_with_the_prompt(self):
        from app import tasks

        with mock.patch('app.tasks.reverse_prompt_video'):
            reverse_id = self.client.post(
                '/api/prompts/reverse',
                json={'video_base64': base64.b64encode(FAKE_MP4).decode('ascii')},
            ).json()['id']

        class _SessionCtx:
            def __init__(self, db):
                self.db = db

            def __enter__(self):
                return self.db

            def __exit__(self, *exc):
                return False

        reading = ReverseReading(keyword='WATCH', prompt='[0.0s–4.0s] a watch.', model='g', raw='')
        with mock.patch.object(tasks, 'SessionLocal', lambda: _SessionCtx(self.db)), \
                mock.patch('app.prompts.reverse_prompt.describe_video', return_value=reading), \
                mock.patch('app.prompts.video_creator.create_reel', side_effect=RuntimeError('no engine')), \
                mock.patch('app.prompts.post_reel.probe', return_value=mock.Mock(duration_s=4.0)), \
                mock.patch('app.prompts.pipeline.ingest', return_value=(None, 'rejected')), \
                mock.patch('app.tasks.console_log'):
            result = tasks.reverse_prompt_video.run(reverse_id)
        self.assertTrue(result['ok'], result)
        row = self.db.get(ReversePrompt, reverse_id)
        self.assertEqual(row.status, 'done')
        self.assertIn('no engine', row.reel_error)
        self.assertEqual(row.keyword, 'WATCH')
        self.assertIsNone(row.reel_key)


if __name__ == '__main__':
    unittest.main()
