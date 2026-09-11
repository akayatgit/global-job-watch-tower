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

    def test_parse_reading_salvages_truncated_json_like_prompt_7(self):
        """Reverse #7: Gemini hit the token cap mid-string. json.loads fails,
        and the old fallback stored the wrapper as keyword PRODUCT."""
        truncated = (
            '{\n'
            '  "keyword": "DEITY",\n'
            '  "prompt": "[0.0s–0.8s] An extreme low-angle shot of a bare foot.\\n'
            '[0.8s–1.8s] The foot makes contact with the cracked earth.\\n'
            '[1.8s–3.0s] A slow crane-up begins. The camera'
        )
        self.assertFalse(reverse_prompt.json_reading_complete(truncated))
        reading = reverse_prompt.parse_reading(truncated)
        self.assertEqual(reading.keyword, 'DEITY')
        self.assertTrue(reading.prompt.startswith('[0.0s–0.8s]'))
        self.assertIn('crane-up begins', reading.prompt)
        self.assertTrue(reading.prompt.endswith('The camera'))
        self.assertNotIn('"keyword"', reading.prompt)
        self.assertNotIn('"prompt"', reading.prompt)

    def test_parse_reading_salvages_unescaped_newlines_inside_prompt(self):
        blob = (
            '{\n  "keyword": "RING",\n  "prompt": "[0.0s–1.0s] A gold ring on slate.\n'
            '[1.0s–3.0s] Macro push-in. Style: cinematic realism."\n}'
        )
        reading = reverse_prompt.parse_reading(blob)
        self.assertEqual(reading.keyword, 'RING')
        self.assertIn('Macro push-in', reading.prompt)
        self.assertIn('Style:', reading.prompt)

    def test_build_instruction_carries_every_dimension_and_the_exemplar(self):
        text = reverse_prompt.build_instruction(duration_s=8.0, exemplar='EXEMPLAR BODY')
        self.assertIn('8.0-second', text)
        for dimension in reverse_prompt.DIMENSIONS:
            self.assertIn(dimension.split('(')[0].strip(), text)
        self.assertIn('EXEMPLAR BODY', text)
        self.assertIn('"keyword"', text)
        bundled = reverse_prompt.load_exemplar()
        self.assertIn('pacific chill', bundled.lower())
        self.assertIn('louis vuitton', bundled.lower())


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

    def test_mime_and_vision_payload_never_use_a_nameless_file_handle(self):
        self.assertEqual(reverse_prompt.mime_for_video('clip.mp4'), 'video/mp4')
        self.assertEqual(reverse_prompt.mime_for_video('clip.MOV'), 'video/quicktime')
        self.assertEqual(reverse_prompt.mime_for_video('clip.webm'), 'video/webm')
        self.assertEqual(reverse_prompt.mime_for_video('clip'), 'video/mp4')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source-1-abc.mp4'
            path.write_bytes(FAKE_MP4)
            payload = reverse_prompt.video_input_for_vision(path)
            self.assertTrue(payload.startswith('data:video/mp4;base64,'))
            raw = base64.b64decode(payload.split(',', 1)[1])
            self.assertEqual(raw, FAKE_MP4)
            huge = Path(tmp) / 'huge.mp4'
            huge.write_bytes(FAKE_MP4)
            with mock.patch.object(reverse_prompt, 'DATA_URI_MAX_BYTES', 10):
                self.assertEqual(
                    reverse_prompt.video_input_for_vision(
                        huge, public_url='https://tower.example/api/partner/v1/assets/prompts/d/source-1.mp4',
                    ),
                    'https://tower.example/api/partner/v1/assets/prompts/d/source-1.mp4',
                )

    def test_describe_video_uses_injected_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'clip.mp4'
            path.write_bytes(FAKE_MP4)
            seen: dict = {}

            def run(model, input):
                seen['model'] = model
                seen['keys'] = sorted(input)
                seen['input'] = input
                seen['prompt'] = input['prompt']
                video = input['videos'][0]
                self.assertIsInstance(video, str)
                self.assertTrue(video.startswith('data:video/mp4;base64,'))
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
            self.assertGreaterEqual(seen['input']['max_output_tokens'], 16384)
            self.assertEqual(seen['input']['thinking_budget'], 0)

    def test_resolve_vision_engine_aliases(self):
        self.assertEqual(reverse_prompt.resolve_vision_engine('Gemini'), 'gemini')
        self.assertEqual(reverse_prompt.resolve_vision_engine('GPT-6 Astra'), 'astra')
        self.assertEqual(reverse_prompt.resolve_vision_engine('claude-fable-5'), 'fable')
        self.assertEqual(reverse_prompt.vision_label('astra'), 'GPT-6 Astra')
        with self.assertRaises(reverse_prompt.ReverseError):
            reverse_prompt.resolve_vision_engine('midjourney')

    def test_astra_attempts_send_the_mp4_not_jpegs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'clip.mp4'
            path.write_bytes(FAKE_MP4)
            attempts = reverse_prompt.astra_content_attempts(
                path, public_url=None, user_text='watch this',
            )
            self.assertEqual(attempts[0][0], 'input_video')
            self.assertEqual(attempts[1][0], 'input_file')
            blob = json.dumps(attempts)
            self.assertIn('video/mp4', blob)
            self.assertIn('input_video', blob)
            self.assertNotIn('image_url', blob)
            self.assertNotIn('image/jpeg', blob)
            self.assertNotIn('stills', blob.lower())

    def test_fable_attempts_send_the_mp4_not_jpegs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'clip.mp4'
            path.write_bytes(FAKE_MP4)
            attempts = reverse_prompt.fable_content_attempts(
                path, public_url=None, user_text='watch this',
            )
            self.assertEqual(attempts[0][0], 'video_base64')
            blob = json.dumps(attempts)
            self.assertIn('video/mp4', blob)
            self.assertNotIn('image/jpeg', blob)
            url_attempts = reverse_prompt.fable_content_attempts(
                path, public_url='https://cdn.example.com/clip.mp4', user_text='watch this',
            )
            self.assertEqual(url_attempts[0][0], 'video_url')
            self.assertEqual(url_attempts[0][1][0]['source']['url'], 'https://cdn.example.com/clip.mp4')

    def test_describe_video_astra_sends_the_clip_not_stills(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'clip.mp4'
            path.write_bytes(FAKE_MP4)
            seen: dict = {}

            def complete(*, model, system, user_text, video_path, public_url=None):
                seen['model'] = model
                seen['path'] = Path(video_path)
                seen['user'] = user_text
                seen['public'] = public_url
                self.assertNotIn('stills', user_text.lower())
                self.assertIn('video file', user_text.lower())
                self.assertTrue(system)
                return json.dumps({
                    'keyword': 'DEITY',
                    'prompt': '[0.0s–3.0s] a gold-anklet foot on cracked earth.\nStyle: mythic.',
                })

            with mock.patch('app.prompts.post_reel.sample_frames') as sample:
                reading = reverse_prompt.describe_video(
                    path, duration_s=3.0, engine='astra', complete=complete, exemplar='BAR',
                    public_url='https://cdn.example.com/clip.mp4',
                )
            sample.assert_not_called()
            self.assertEqual(reading.keyword, 'DEITY')
            self.assertEqual(seen['model'], 'gpt-6-astra')
            self.assertEqual(seen['path'], path)
            self.assertEqual(seen['public'], 'https://cdn.example.com/clip.mp4')

    def test_describe_video_fable_uses_injected_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'clip.mp4'
            path.write_bytes(FAKE_MP4)

            def complete(*, model, system, user_text, video_path, public_url=None):
                self.assertEqual(model, 'claude-fable-5')
                self.assertEqual(Path(video_path), path)
                self.assertNotIn('stills', user_text.lower())
                return json.dumps({'keyword': 'RING', 'prompt': '[0.0s–2.0s] a gold ring. Style: macro.'})

            reading = reverse_prompt.describe_video(
                path, duration_s=2.0, engine='fable', complete=complete,
            )
            self.assertEqual(reading.keyword, 'RING')
            self.assertIn('gold ring', reading.prompt)

    def test_openai_complete_falls_through_to_code_interpreter(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'clip.mp4'
            path.write_bytes(FAKE_MP4)
            calls: list[dict] = []

            class Boom(Exception):
                status_code = 400

            class FakeResponses:
                def create(self, **kwargs):
                    calls.append(kwargs)
                    tools = kwargs.get('tools') or []
                    if not any(t.get('type') == 'code_interpreter' for t in tools):
                        raise Boom('unsupported video input')
                    return SimpleNamespace(output_text=json.dumps({
                        'keyword': 'WATCH',
                        'prompt': '[0.0s–1.0s] a steel watch. Style: macro.',
                    }))

            class FakeFiles:
                def __init__(self):
                    self.deleted = []

                def create(self, **kwargs):
                    self.last_create = kwargs
                    return SimpleNamespace(id='file-9')

                def delete(self, file_id):
                    self.deleted.append(file_id)

            files = FakeFiles()
            client = SimpleNamespace(responses=FakeResponses(), files=files)
            text = reverse_prompt._openai_complete(
                model='gpt-6-astra',
                system='sys',
                user_text='watch the clip',
                video_path=path,
                client=client,
            )
            self.assertIn('steel watch', text)
            self.assertGreaterEqual(len(calls), 3)
            self.assertTrue(any(
                (c.get('tools') or [{}])[0].get('type') == 'code_interpreter' for c in calls
            ))
            blob = json.dumps(calls)
            self.assertNotIn('image_url', blob)
            self.assertNotIn('image/jpeg', blob)
            self.assertEqual(files.deleted, ['file-9'])

    def test_anthropic_complete_falls_through_to_container_upload(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'clip.mp4'
            path.write_bytes(FAKE_MP4)
            calls: list[dict] = []

            class Boom(Exception):
                status_code = 400

            class FakeMessages:
                def create(self, **kwargs):
                    calls.append(kwargs)
                    content = kwargs['messages'][0]['content']
                    if not any(
                        (block.get('type') if isinstance(block, dict) else getattr(block, 'type', ''))
                        == 'container_upload'
                        for block in content
                    ):
                        raise Boom('video content type is not supported')
                    return SimpleNamespace(content=[
                        SimpleNamespace(type='text', text=json.dumps({
                            'keyword': 'RING',
                            'prompt': '[0.0s–2.0s] a gold ring. Style: macro.',
                        })),
                    ])

            class FakeFiles:
                def __init__(self):
                    self.deleted = []

                def upload(self, **kwargs):
                    return SimpleNamespace(id='file_fable')

                def delete(self, file_id):
                    self.deleted.append(file_id)

            files = FakeFiles()
            client = SimpleNamespace(messages=FakeMessages(), files=files)
            text = reverse_prompt._anthropic_complete(
                model='claude-fable-5',
                system='sys',
                user_text='watch the clip',
                video_path=path,
                client=client,
            )
            self.assertIn('gold ring', text)
            self.assertTrue(any(
                t.get('type') == 'code_execution_20250825'
                for c in calls for t in (c.get('tools') or [])
            ))
            blob = json.dumps(calls)
            self.assertNotIn('image/jpeg', blob)
            self.assertEqual(files.deleted, ['file_fable'])

    def test_describe_video_retries_truncated_json_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'clip.mp4'
            path.write_bytes(FAKE_MP4)
            calls: list[dict] = []

            def run(model, input):
                calls.append(input)
                if len(calls) == 1:
                    return (
                        '{"keyword": "DEITY", "prompt": "[0.0s–0.8s] a descending foot.\\n'
                        '[1.8s–3.0s] The camera'
                    )
                return json.dumps({
                    'keyword': 'DEITY',
                    'prompt': (
                        '[0.0s–0.8s] a descending foot.\n'
                        '[0.8s–1.8s] impact burst of gold.\n'
                        '[1.8s–3.0s] crane-up reveals saffron dhoti.\n'
                        'Style: mythic cinematic realism.'
                    ),
                })

            logs: list[str] = []
            reading = reverse_prompt.describe_video(
                path, duration_s=3.0, run=run, exemplar='BAR', log=logs.append,
            )
            self.assertEqual(len(calls), 2)
            self.assertIn('cut off', calls[1]['prompt'].lower())
            self.assertEqual(reading.keyword, 'DEITY')
            self.assertIn('Style:', reading.prompt)
            self.assertTrue(any('truncated' in line for line in logs))


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
                json={'source_url': IG_URL, 'chat_id': '100', 'title': 'CINEMATIC AI AD'},
            )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body['status'], 'queued')
        self.assertEqual(body['platform'], 'instagram')
        self.assertEqual(body['source_url'], 'https://www.instagram.com/reel/AbC123xyz/')
        self.assertEqual(body['header_title'], 'CINEMATIC AI AD')
        self.assertEqual(body['vision_engine'], 'gemini')
        queued.delay.assert_called_once_with(body['id'])
        listed = self.client.get('/api/prompts/reverse').json()
        self.assertEqual(listed['total'], 1)
        self.assertEqual(self.client.get(f"/api/prompts/reverse/{body['id']}").json()['id'], body['id'])

    def test_post_stores_astra_vision_engine(self):
        with mock.patch('app.tasks.reverse_prompt_video') as queued:
            response = self.client.post(
                '/api/prompts/reverse',
                json={'source_url': IG_URL, 'vision_engine': 'GPT-6 Astra'},
            )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['vision_engine'], 'astra')
        queued.delay.assert_called_once()

    def test_post_rejects_unknown_vision_engine(self):
        response = self.client.post(
            '/api/prompts/reverse',
            json={'source_url': IG_URL, 'vision_engine': 'midjourney'},
        )
        self.assertEqual(response.status_code, 422)

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
