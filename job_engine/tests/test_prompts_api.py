"""Prompt Tower API (/api/prompts/*) + partner /api/partner/v1/prompts."""

from __future__ import annotations

import base64
import tempfile
import unittest
from datetime import datetime, timezone
from io import BytesIO
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.api import partner, prompts as prompts_api
from app.db import Base, get_db
from app.models import PromptRender, VideoPrompt
from tests.test_video_prompts import COFFEE, PERFUME, SNEAKER, fake_chat_factory


def make_session():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def make_client(db):
    app = FastAPI()
    app.include_router(prompts_api.router)
    app.include_router(partner.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def png_b64(size=(120, 200)) -> str:
    buffer = BytesIO()
    Image.new('RGB', size, (30, 180, 120)).save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode('ascii')


class PromptsApiTests(unittest.TestCase):
    def setUp(self):
        self.db = make_session()
        self.client = make_client(self.db)
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(config, 'AI_REQUIREMENTS_MODE', 'on'),
            mock.patch.object(config, 'PARTNER_ASSETS_DIR', self.tmp.name),
            mock.patch.object(config, 'PARTNER_PUBLIC_BASE_URL', 'https://tower.example'),
            mock.patch.object(config, 'PARTNER_API_TOKEN', 'secret-token'),
            mock.patch('app.prompts.scoring._chat', fake_chat_factory(82, 76)),
            mock.patch('app.thermal.ollama_path_open', return_value=True),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def _seed_shortlist(self):
        from app.prompts.sources import Candidate

        response = self.client.post('/api/prompts/scan', json={'inline': True, 'force': False})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_today_empty_then_populated_by_inline_scan(self):
        self.assertEqual(self.client.get('/api/prompts/today').json()['total'], 0)
        with mock.patch('app.prompts.pipeline.gather_candidates') as gather:
            from app.prompts.sources import Candidate

            gather.return_value = [
                Candidate(text=PERFUME, source='reddit', author='a', source_url='https://r/x'),
                Candidate(text=COFFEE, source='web'),
            ]
            summary = self._seed_shortlist()
        self.assertFalse(summary['queued'])
        self.assertEqual(summary['shortlisted'], 2)
        today = self.client.get('/api/prompts/today').json()
        self.assertEqual(today['total'], 2)
        self.assertEqual(today['prompts'][0]['rank'], 1)
        self.assertLessEqual(len(today['prompts'][0]['text']), 280)
        full = self.client.get('/api/prompts/today', params={'full': 1}).json()
        self.assertGreater(len(full['prompts'][0]['text']), 280)
        self.assertEqual(self.client.get('/api/prompts/today', params={'day': 'nope'}).status_code, 422)

    def test_scan_queues_to_worker_by_default(self):
        with mock.patch('app.tasks.daily_prompt_pipeline') as task:
            response = self.client.post('/api/prompts/scan', json={})
        self.assertEqual(response.json(), {'queued': True})
        task.delay.assert_called_once_with(force=False)

    def test_ingest_scores_and_rejects_captions(self):
        response = self.client.post('/api/prompts/ingest', json={'text': PERFUME, 'author': 'ashok'})
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body['outcome'], 'created')
        self.assertEqual(body['prompt']['source'], 'manual')
        self.assertEqual(body['prompt']['ai_detail'], 82.0)
        self.assertIsNotNone(body['prompt']['final_score'])
        again = self.client.post('/api/prompts/ingest', json={'text': PERFUME})
        self.assertEqual(again.json()['outcome'], 'duplicate')
        bad = self.client.post('/api/prompts/ingest', json={'text': 'Comment PERFUME for prompts'})
        self.assertEqual(bad.status_code, 422)

    def test_rate_performance_posted_and_stats(self):
        prompt_id = self.client.post('/api/prompts/ingest', json={'text': SNEAKER}).json()['prompt']['id']
        self.assertEqual(self.client.post(f'/api/prompts/{prompt_id}/rate', json={'rating': 9}).status_code, 422)
        rated = self.client.post(f'/api/prompts/{prompt_id}/rate', json={'rating': 5}).json()
        self.assertEqual(rated['rating'], 5)
        self.assertTrue(rated['exemplar'])
        self.assertEqual(self.client.post(f'/api/prompts/{prompt_id}/performance', json={}).status_code, 422)
        perf = self.client.post(f'/api/prompts/{prompt_id}/performance', json={'likes': 120, 'comments': 9}).json()
        self.assertEqual(perf['performance'], {'likes': 120, 'comments': 9})
        self.assertEqual(perf['status'], 'posted')
        self.assertEqual(self.client.post('/api/prompts/999/posted').status_code, 404)
        stats = self.client.get('/api/prompts/stats').json()
        self.assertEqual(stats['total'], 1)
        self.assertEqual(stats['exemplars'], 1)
        self.assertEqual(stats['posted'], 1)
        self.assertEqual(stats['by_source'], {'manual': 1})
        self.assertIsNotNone(stats['baseline_mean'])

    def test_render_stores_image_and_card_then_queues_video(self):
        prompt_id = self.client.post('/api/prompts/ingest', json={'text': PERFUME}).json()['prompt']['id']
        with mock.patch('app.tasks.render_prompt_video') as task:
            response = self.client.post(
                f'/api/prompts/{prompt_id}/render',
                json={'image_base64': png_b64(), 'chat_id': '42', 'content_type': 'image/png'},
            )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body['status'], 'queued')
        task.delay.assert_called_once_with(body['id'])
        self.assertTrue(body['product_image_key'].endswith('.png'))
        self.assertTrue(body['card_image_url'].startswith('https://tower.example/api/partner/v1/assets/prompts/'))
        row = self.db.get(PromptRender, body['id'])
        self.assertEqual(row.chat_id, '42')
        with Image.open(f"{self.tmp.name}/{row.card_image_key}") as card:
            self.assertEqual(card.size, (1080, 1920))
        status = self.client.get(f"/api/prompts/renders/{body['id']}").json()
        self.assertEqual(status['status'], 'queued')
        self.assertEqual(self.client.get('/api/prompts/renders/999').status_code, 404)

    def test_render_rejects_bad_images(self):
        prompt_id = self.client.post('/api/prompts/ingest', json={'text': PERFUME}).json()['prompt']['id']
        self.assertEqual(
            self.client.post(f'/api/prompts/{prompt_id}/render', json={'image_base64': '!!notb64'}).status_code, 422,
        )
        junk = base64.b64encode(b'not an image at all').decode()
        self.assertEqual(
            self.client.post(f'/api/prompts/{prompt_id}/render', json={'image_base64': junk}).status_code, 422,
        )
        self.assertEqual(
            self.client.post('/api/prompts/999/render', json={'image_base64': png_b64()}).status_code, 404,
        )

    def test_render_task_end_to_end_with_fake_replicate(self):
        from app import tasks

        prompt_id = self.client.post('/api/prompts/ingest', json={'text': PERFUME}).json()['prompt']['id']
        with mock.patch('app.tasks.render_prompt_video') as queued:
            render_id = self.client.post(
                f'/api/prompts/{prompt_id}/render', json={'image_base64': png_b64()},
            ).json()['id']
        queued.delay.assert_called_once()

        class _SessionCtx:
            def __init__(self, db):
                self.db = db

            def __enter__(self):
                return self.db

            def __exit__(self, *exc):
                return False

        from app.prompts import video_creator

        real_create = video_creator.create_video

        def fake_run(model, input):
            return [BytesIO(b'\x01' * 5000)]

        def create_with_fake_replicate(prompt_text, image_path, *, prompt_id):
            return real_create(prompt_text, image_path, prompt_id=prompt_id, run=fake_run)

        with mock.patch.object(tasks, 'SessionLocal', lambda: _SessionCtx(self.db)), \
                mock.patch.object(video_creator, 'create_video', side_effect=create_with_fake_replicate), \
                mock.patch.object(config, 'REPLICATE_VIDEO_MODEL', 'kwaivgi/kling-v2.1'), \
                mock.patch('app.tasks.console_log'):
            result = tasks.render_prompt_video.run(render_id)
        self.assertTrue(result['ok'], result)
        row = self.db.get(PromptRender, render_id)
        self.assertEqual(row.status, 'done')
        self.assertTrue(row.video_url.endswith('.mp4'))
        self.assertEqual(row.model, 'kwaivgi/kling-v2.1')

    def test_partner_prompts_endpoint_is_token_gated_and_verbatim(self):
        with mock.patch('app.prompts.pipeline.gather_candidates') as gather:
            from app.prompts.sources import Candidate

            gather.return_value = [Candidate(text=SNEAKER, source='instagram', source_url='https://www.instagram.com/p/abc/')]
            self._seed_shortlist()
        self.assertEqual(self.client.get('/api/partner/v1/prompts').status_code, 401)
        response = self.client.get('/api/partner/v1/prompts', headers={'Authorization': 'Bearer secret-token'})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['total'], 1)
        item = body['prompts'][0]
        self.assertEqual(item['text'], self.db.query(VideoPrompt).one().text)
        self.assertEqual(item['source_url'], 'https://www.instagram.com/p/abc/')
        self.assertIsNone(item['video_url'])
        self.assertEqual(
            self.client.get('/api/partner/v1/prompts', params={'day': 'x'}, headers={'Authorization': 'Bearer secret-token'}).status_code,
            422,
        )


if __name__ == '__main__':
    unittest.main()
