"""Partner asset storage tests (contract 2026-08-14, Vercel-only ruling).

Covers: the PUT auth gate (503 disabled / 401 wrong / 200 correct), key
validation (charset, traversal, dot-leading segments), upload → public GET
round trip with stored Content-Type, idempotent overwrite, 404 on missing,
HTTP Range → 206 (iOS Safari video requirement), the 100 MB cap via
Content-Length, and that internal .meta/.tmp dirs are unreachable.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import partner, partner_assets


AUTH = {'Authorization': 'Bearer secret-token'}


class PartnerAssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app = FastAPI()
        app.include_router(partner_assets.router)
        self.client = TestClient(app)
        self._patches = [
            mock.patch.object(partner.config, 'PARTNER_API_TOKEN', 'secret-token'),
            mock.patch.object(
                partner_assets.config, 'PARTNER_ASSETS_DIR', self.tmp.name,
            ),
            mock.patch.object(
                partner_assets.config,
                'PARTNER_PUBLIC_BASE_URL',
                'https://tower.jobmaster.agency',
            ),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    # ---- auth gate ----

    def test_put_requires_token(self):
        self.assertEqual(
            self.client.put(
                '/api/partner/v1/assets/job-reel/status/x.json', content=b'x',
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.put(
                '/api/partner/v1/assets/job-reel/status/x.json',
                content=b'x',
                headers={'Authorization': 'Bearer wrong'},
            ).status_code,
            401,
        )

    def test_disabled_when_token_unset(self):
        with mock.patch.object(partner.config, 'PARTNER_API_TOKEN', ''):
            response = self.client.put(
                '/api/partner/v1/assets/job-reel/status/x.json',
                content=b'x',
                headers=AUTH,
            )
        self.assertEqual(response.status_code, 503)

    # ---- key validation ----

    def test_traversal_and_bad_keys_rejected(self):
        bad_keys = (
            'job-reel/../../../etc/passwd',
            'job-reel/..',
            '/etc/passwd',
            'job-reel//x.mp4',
            'job-reel/.hidden/x.mp4',
            '.meta/job-reel/x.mp4',
            '.tmp/x',
            'Job-Reel/UPPER.mp4',
            'a',
        )
        for key in bad_keys:
            response = self.client.put(
                f'/api/partner/v1/assets/{key}', content=b'x', headers=AUTH,
            )
            # 400 = our validator; 404 = the http client/router normalized
            # '..' away before the route matched. Both are safe rejections —
            # what matters is no 2xx and no file write.
            self.assertIn(response.status_code, (400, 404), key)
            self.assertIn(
                self.client.get(f'/api/partner/v1/assets/{key}').status_code,
                (400, 404),
                key,
            )
        self.assertFalse((Path(self.tmp.name).parent / 'etc').exists())

    # ---- round trip ----

    def test_upload_then_public_get_round_trip(self):
        put = self.client.put(
            '/api/partner/v1/assets/job-reel/status/smoke-test-1.json',
            content=b'hello',
            headers={**AUTH, 'Content-Type': 'text/plain'},
        )
        self.assertEqual(put.status_code, 200)
        payload = put.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['size'], 5)
        self.assertEqual(
            payload['url'],
            'https://tower.jobmaster.agency/api/partner/v1/assets/job-reel/status/smoke-test-1.json',
        )

        get = self.client.get('/api/partner/v1/assets/job-reel/status/smoke-test-1.json')
        self.assertEqual(get.status_code, 200)
        self.assertEqual(get.content, b'hello')
        self.assertTrue(get.headers['content-type'].startswith('text/plain'))
        self.assertEqual(get.headers['cache-control'], 'public, max-age=3600')

    def test_overwrite_is_idempotent(self):
        key = '/api/partner/v1/assets/job-reel/status/reel-1.json'
        self.client.put(key, content=b'{"status":"rendering"}', headers=AUTH)
        self.client.put(key, content=b'{"status":"done"}', headers=AUTH)
        self.assertEqual(self.client.get(key).content, b'{"status":"done"}')

    def test_missing_key_is_404(self):
        self.assertEqual(
            self.client.get('/api/partner/v1/assets/job-reel/videos/nope.mp4').status_code,
            404,
        )

    # ---- iOS Safari requirement ----

    def test_range_request_returns_206_partial(self):
        self.client.put(
            '/api/partner/v1/assets/job-reel/backgrounds/bg-1.mp4',
            content=b'0123456789',
            headers={**AUTH, 'Content-Type': 'video/mp4'},
        )
        response = self.client.get(
            '/api/partner/v1/assets/job-reel/backgrounds/bg-1.mp4',
            headers={'Range': 'bytes=0-3'},
        )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b'0123')
        self.assertIn('content-range', {k.lower() for k in response.headers})

    # ---- size cap ----

    def test_declared_oversize_is_413(self):
        response = self.client.put(
            '/api/partner/v1/assets/job-reel/videos/huge.mp4',
            content=b'x',
            headers={**AUTH, 'Content-Length': str(200 * 1024 * 1024)},
        )
        self.assertEqual(response.status_code, 413)

    def test_streamed_oversize_is_413(self):
        with mock.patch.object(partner_assets, 'MAX_ASSET_BYTES', 4):
            response = self.client.put(
                '/api/partner/v1/assets/job-reel/videos/big.mp4',
                content=b'123456789',
                headers=AUTH,
            )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(
            self.client.get('/api/partner/v1/assets/job-reel/videos/big.mp4').status_code,
            404,
        )

    # ---- content-type fallback ----

    def test_mp4_content_type_guessed_when_header_absent(self):
        self.client.put(
            '/api/partner/v1/assets/job-reel/videos/reel-2.mp4',
            content=b'fakevideo',
            headers=AUTH,
        )
        response = self.client.get('/api/partner/v1/assets/job-reel/videos/reel-2.mp4')
        self.assertEqual(response.headers['content-type'], 'video/mp4')

    def test_files_land_under_the_assets_root(self):
        self.client.put(
            '/api/partner/v1/assets/job-reel/status/where.json',
            content=b'{}',
            headers=AUTH,
        )
        self.assertTrue(
            (Path(self.tmp.name) / 'job-reel' / 'status' / 'where.json').is_file(),
        )


if __name__ == '__main__':
    unittest.main()
