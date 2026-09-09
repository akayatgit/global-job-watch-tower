"""Prompt Tower core (pivot 2026-09-09): normalize → sources → RAG →
Hermes scoring → daily top-10 → feedback learning → video creator/card.

Everything runs offline: sqlite in-memory, a fake model, a fake Replicate.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest import mock

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.db import Base
from app.models import PromptShortlist, VideoPrompt
from app.prompts import normalize, pipeline, post_card, rag, scoring, sources, video_creator
from app.prompts.sources import Candidate

PERFUME = (
    'Create a 10-second vertical 9:16 ultra-premium photorealistic CGI luxury-fragrance '
    'commercial using the uploaded perfume bottle and vivid green cylindrical travel case '
    'as the strict hero-product references. Preserve the exact transparent rounded-rectangular '
    'bottle geometry, thick clear glass base, black circular stacked cap and engraved front '
    'typography. Render at 30 fps with a virtual full-frame camera using 70–130 mm lenses, '
    '1/60 s shutter, ISO 100–200, 4800–5200 K white balance, apertures around f/5.6–f/8. '
    'Soft studio lighting with long shadows; slow orbit around the bottle, gentle reflections '
    'on the glass, then a slow push-in reveal of the cap. Do not redesign the bottle or change branding.'
)
COFFEE = (
    'A 8-second 9:16 product film for a cold brew coffee can. Macro camera on a 100 mm lens, '
    'shallow depth of field, condensation droplets rolling down the matte black can as it slowly '
    'rotates on a wet slate surface. Rim light from the left, warm golden hour backlight, '
    'reflections in the puddle. Ice cubes fall in slow motion and splash; the logo stays sharp '
    'and unchanged. End on a push-in to the label. Photorealistic, 4K, no text overlays.'
)
SNEAKER = (
    'Vertical 9:16 ten second sneaker commercial. Start with a low tracking shot across a wet '
    'neon-lit street at night, the white leather sneaker floats and rotates slowly above the '
    'puddle while rain droplets bounce off the sole. 35 mm lens, 24 fps, cinematic depth of field, '
    'strong cyan and magenta rim lights, soft shadows. Keep the exact shoe geometry, stitching and '
    'brand logo untouched. Final beat: the shoe lands, splash, camera pushes in on the logo.'
)
CAPTION = 'Comment PERFUME for the prompt! Follow for more AI video prompts every day.'


def make_session():
    engine = create_engine(
        'sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def fake_chat_factory(detail: float = 84, flow: float = 78):
    def _chat(_prompt: str) -> str:
        return json.dumps({'detail': detail, 'flow': flow, 'reasons': ['lens + shutter stated', 'orbit then reveal']})
    return _chat


class NormalizeTests(unittest.TestCase):
    def test_real_prompt_reads_as_prompt_with_category_and_title(self):
        reading = normalize.read_prompt(PERFUME)
        self.assertTrue(reading.is_prompt)
        self.assertEqual(reading.category, 'perfume')
        self.assertGreaterEqual(reading.heuristic_score, 80)
        self.assertTrue(reading.title.startswith('10-second vertical'))
        self.assertEqual(len(reading.fingerprint), 40)

    def test_caption_is_not_a_prompt(self):
        reading = normalize.read_prompt(CAPTION)
        self.assertFalse(reading.is_prompt)
        self.assertLess(reading.heuristic_score, 40)

    def test_fingerprint_ignores_whitespace_case_and_punctuation(self):
        a = normalize.fingerprint('Slow ORBIT, around the bottle.')
        b = normalize.fingerprint('slow orbit   around the bottle')
        self.assertEqual(a, b)

    def test_model_hint_detects_veo_and_kling_only_as_words(self):
        self.assertEqual(normalize.detect_model_hint('made with Veo 3 today'), 'veo')
        self.assertEqual(normalize.detect_model_hint('kling ai render'), 'kling')
        self.assertIsNone(normalize.detect_model_hint('a sparkling drink'))  # 'kling' inside a word

    def test_clean_text_strips_urls_and_engagement_bait(self):
        text = normalize.clean_text('Prompt: Slow orbit https://x.co/abc\nComment PERFUME for prompts\nsoft light')
        self.assertNotIn('http', text)
        self.assertNotIn('Comment', text)
        self.assertTrue(text.startswith('Slow orbit'))

    def test_heuristic_rewards_numbers_and_flow(self):
        with_numbers, _f, _r = normalize.heuristic_score(COFFEE)
        stripped, _f, reasons = normalize.heuristic_score(
            'camera light glass rotate product ' * 12,
        )
        self.assertGreater(with_numbers, stripped)
        self.assertIn('single run-on sentence — weak shot flow', reasons)


class SourcesTests(unittest.TestCase):
    def test_reddit_listing_yields_candidates_with_provenance(self):
        payload = {
            'data': {'children': [
                {'data': {
                    'selftext': f'Here is my Veo 3 prompt:\n\n```\n{PERFUME}\n```\nEnjoy',
                    'title': 'LV perfume ad recreated',
                    'permalink': '/r/aivideo/comments/abc/lv/',
                    'author': 'promptsmith',
                    'created_utc': 1_757_000_000,
                }},
                {'data': {'selftext': CAPTION, 'title': 'meh', 'permalink': '/r/aivideo/x/', 'author': 'z'}},
            ]},
        }
        out = sources.reddit_candidates(['aivideo'], fetch=lambda url: json.dumps(payload))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].source, 'reddit')
        self.assertEqual(out[0].author, 'promptsmith')
        self.assertEqual(out[0].source_url, 'https://www.reddit.com/r/aivideo/comments/abc/lv/')
        self.assertEqual(out[0].posted_at.tzinfo, timezone.utc)
        self.assertIn('Preserve the exact', out[0].text)

    def test_reddit_failure_is_swallowed(self):
        def boom(_url):
            raise OSError('rate limited')
        self.assertEqual(sources.reddit_candidates(['aivideo'], fetch=boom), [])

    def test_web_page_pre_blocks_and_body_paragraphs(self):
        page = f'<html><body><h1>Prompts</h1><pre>{PERFUME}</pre><p>{CAPTION}</p><p>{COFFEE}</p></body></html>'
        out = sources.web_candidates(['https://promptbase.com/x'], fetch=lambda url: page)
        texts = [c.text for c in out]
        self.assertEqual(len(out), 2)
        self.assertTrue(all(c.source == 'promptbase' for c in out))
        self.assertTrue(any('fragrance' in t for t in texts))
        self.assertTrue(any('cold brew' in t for t in texts))

    def test_instagram_captions_parsed_from_embedded_json(self):
        caption = json.dumps(PERFUME)[1:-1]
        html = (
            '{"shortcode":"C9abcXYZ12","caption":{"text":"' + caption + '"}}'
            '{"shortcode":"C9defXYZ34","caption":{"text":"just vibes"}}'
        )
        out = sources.instagram_candidates(['veo3prompt'], fetch=lambda url: html)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].source, 'instagram')
        self.assertEqual(out[0].source_url, 'https://www.instagram.com/p/C9abcXYZ12/')

    def test_manual_candidate_rejects_captions(self):
        self.assertIsNone(sources.manual_candidate(CAPTION))
        candidate = sources.manual_candidate(PERFUME, author='ashok')
        self.assertEqual(candidate.source, 'manual')

    def test_gather_uses_config_and_never_raises(self):
        with mock.patch.object(config, 'PROMPT_REDDIT_SUBS', 'aivideo'), \
                mock.patch.object(config, 'PROMPT_WEB_URLS', 'https://example.com/prompts'), \
                mock.patch.object(config, 'PROMPT_INSTAGRAM_TAGS', ''):
            calls: list[str] = []

            def fetch(url: str) -> str:
                calls.append(url)
                if 'reddit' in url:
                    return json.dumps({'data': {'children': []}})
                return f'<pre>{SNEAKER}</pre>'
            out = sources.gather_candidates(fetch=fetch)
        self.assertEqual(len(out), 1)
        self.assertEqual(len(calls), 2)


class RagTests(unittest.TestCase):
    def test_hashed_embedding_is_unit_and_deterministic(self):
        a = rag.hashed_embedding(PERFUME)
        b = rag.hashed_embedding(PERFUME)
        self.assertEqual(a, b)
        self.assertAlmostEqual(sum(x * x for x in a), 1.0, places=3)
        self.assertGreater(rag.cosine(a, rag.hashed_embedding(PERFUME + ' extra word')), 0.9)
        self.assertLess(rag.cosine(a, rag.hashed_embedding(SNEAKER)), 0.6)

    def test_performance_score_and_promotion(self):
        self.assertIsNone(rag.performance_score(None, None))
        self.assertEqual(rag.performance_score(5, None), 60.0)
        self.assertGreater(rag.performance_score(None, {'likes': 500, 'comments': 40, 'saves': 60}), 20)
        db = make_session()
        row = VideoPrompt(fingerprint='f1', text=PERFUME, source='manual', collected_at=datetime.now(timezone.utc), rating=4)
        db.add(row)
        db.commit()
        self.assertEqual(rag.promote_winners(db), 1)
        self.assertTrue(row.exemplar)
        self.assertEqual(rag.promote_winners(db), 0)

    def test_baseline_and_outlier(self):
        db = make_session()
        for index, score in enumerate((70.0, 72.0, 74.0)):
            db.add(VideoPrompt(
                fingerprint=f'w{index}', text=PERFUME, source='manual',
                collected_at=datetime.now(timezone.utc), exemplar=True, final_score=score,
            ))
        db.commit()
        base = rag.baseline(db)
        self.assertEqual(base.count, 3)
        self.assertEqual(base.mean, 72.0)
        self.assertTrue(base.is_outlier(90.0))   # 72 + max(std=1.6, floor 5) = 77
        self.assertFalse(base.is_outlier(76.0))
        self.assertFalse(rag.Baseline(count=1, mean=50.0, std=0.0).is_outlier(99.0))


class ScoringTests(unittest.TestCase):
    def test_validate_ai_reply_strict(self):
        self.assertIsNone(scoring.validate_ai_reply(''))
        self.assertIsNone(scoring.validate_ai_reply('{"detail": 120, "flow": 50}'))
        self.assertIsNone(scoring.validate_ai_reply('{"detail": "high", "flow": 50}'))
        self.assertIsNone(scoring.validate_ai_reply('{"detail": true, "flow": 50}'))
        parsed = scoring.validate_ai_reply('noise {"detail": 80, "flow": 70.5, "reasons": ["a", 3, "b"]} tail')
        self.assertEqual(parsed.detail, 80.0)
        self.assertEqual(parsed.flow, 70.5)
        self.assertEqual(parsed.reasons, ['a', 'b'])
        self.assertAlmostEqual(parsed.score, 75.25, places=1)

    def test_blend_caps_unjudged_prompts(self):
        self.assertEqual(scoring.blend(96.0, None), 70.0)
        judged = scoring.blend(96.0, scoring.AIScore(detail=80, flow=70))
        self.assertEqual(judged, round(0.35 * 96 + 0.65 * 75, 1))

    def test_build_prompt_includes_exemplars(self):
        text = scoring.build_prompt(COFFEE, [(PERFUME, 88.0)])
        self.assertIn('Calibration', text)
        self.assertIn('(88/100)', text)
        self.assertIn('cold brew', text)

    def test_ai_score_uses_injected_chat_and_retries_once(self):
        calls = []

        def flaky(prompt):
            calls.append(prompt)
            return 'garbage' if len(calls) == 1 else '{"detail": 60, "flow": 65, "reasons": []}'
        with mock.patch.object(config, 'AI_REQUIREMENTS_MODE', 'on'):
            verdict = scoring.ai_score(COFFEE, [], chat=flaky)
        self.assertEqual(len(calls), 2)
        self.assertEqual(verdict.score, 62.5)

    def test_ai_off_returns_none(self):
        with mock.patch.object(config, 'AI_REQUIREMENTS_MODE', 'off'):
            self.assertIsNone(scoring.ai_score(COFFEE, [], chat=fake_chat_factory()))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.db = make_session()
        self.patches = [
            mock.patch.object(config, 'AI_REQUIREMENTS_MODE', 'on'),
            mock.patch.object(config, 'PROMPT_MIN_SCORE', 55.0),
            mock.patch.object(config, 'PROMPT_SHORTLIST_SIZE', 10),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()

    def test_ingest_dedupes_exact_and_rejects_captions(self):
        row, outcome = pipeline.ingest(self.db, Candidate(text=PERFUME, source='reddit'))
        self.assertEqual(outcome, 'created')
        again, outcome2 = pipeline.ingest(self.db, Candidate(text=PERFUME.upper(), source='web'))
        self.assertEqual(outcome2, 'duplicate')
        self.assertEqual(again.id, row.id)
        self.assertEqual(pipeline.ingest(self.db, Candidate(text=CAPTION, source='reddit')), (None, 'rejected'))

    def test_near_duplicate_detected_by_embedding(self):
        pipeline.ingest(self.db, Candidate(text=PERFUME, source='reddit'))
        near, outcome = pipeline.ingest(self.db, Candidate(text=PERFUME + ' Extra closing beat.', source='instagram'))
        self.assertEqual(outcome, 'near_duplicate')
        self.assertEqual(near.source, 'reddit')

    def test_run_daily_scores_shortlists_and_is_idempotent(self):
        candidates = [
            Candidate(text=PERFUME, source='reddit', author='a'),
            Candidate(text=COFFEE, source='web'),
            Candidate(text=SNEAKER, source='instagram'),
            Candidate(text=CAPTION, source='reddit'),
        ]
        summary = pipeline.run_daily(self.db, day=date(2026, 9, 9), candidates=candidates, chat=fake_chat_factory())
        self.assertEqual(summary['created'], 3)
        self.assertEqual(summary['rejected'], 1)
        self.assertEqual(summary['scored'], 3)
        self.assertEqual(summary['shortlisted'], 3)
        self.assertEqual([t['rank'] for t in summary['top']], [1, 2, 3])
        self.assertTrue(all(t['status'] == 'shortlisted' for t in summary['top']))
        # Second run same day: nothing new, shortlist untouched
        again = pipeline.run_daily(self.db, day=date(2026, 9, 9), candidates=candidates, chat=fake_chat_factory())
        self.assertEqual(again['created'], 0)
        self.assertEqual(again['duplicate'], 3)
        self.assertEqual(again['shortlisted'], 3)
        self.assertEqual(self.db.query(PromptShortlist).count(), 3)

    def test_shortlist_respects_min_score_and_source_cap(self):
        texts = [f'{SNEAKER} Variation {i}: extra {"detail " * i}shot of the {i} mm lens.' for i in range(1, 6)]
        for text in texts:
            row = VideoPrompt(
                fingerprint=normalize.fingerprint(text), text=text, source='reddit',
                collected_at=datetime.now(timezone.utc), embedding=None,
                heuristic_score=90.0, final_score=80.0, scored_at=datetime.now(timezone.utc), status='new',
            )
            self.db.add(row)
        self.db.add(VideoPrompt(
            fingerprint='low', text=COFFEE, source='web', collected_at=datetime.now(timezone.utc),
            heuristic_score=40.0, final_score=40.0, scored_at=datetime.now(timezone.utc), status='new',
        ))
        self.db.add(VideoPrompt(
            fingerprint='manual', text=PERFUME, source='manual', collected_at=datetime.now(timezone.utc),
            heuristic_score=90.0, final_score=60.0, scored_at=datetime.now(timezone.utc), status='new',
        ))
        self.db.commit()
        shortlist = pipeline.build_shortlist(self.db, datetime.now(timezone.utc).date())
        sources_used = [p.source for _e, p in shortlist]
        self.assertEqual(sources_used.count('reddit'), 3)
        self.assertIn('manual', sources_used)
        self.assertNotIn('web', sources_used)  # below PROMPT_MIN_SCORE

    def test_outliers_rank_first_and_learn_from_feedback(self):
        # Seed proven winners at ~70 so a 90 is an outlier and a 74 is not
        for index in range(3):
            self.db.add(VideoPrompt(
                fingerprint=f'win{index}', text=f'{PERFUME} winner {index}', source='manual',
                collected_at=datetime.now(timezone.utc) - timedelta(days=3),
                exemplar=True, final_score=70.0, status='posted',
            ))
        self.db.commit()
        strong, _ = pipeline.ingest(self.db, Candidate(text=SNEAKER, source='reddit'))
        modest, _ = pipeline.ingest(self.db, Candidate(text=COFFEE, source='web'))
        pipeline.score_prompt(self.db, strong, chat=fake_chat_factory(95, 95))
        pipeline.score_prompt(self.db, modest, chat=fake_chat_factory(60, 60))
        self.db.commit()
        self.assertTrue(strong.is_outlier)
        self.assertFalse(modest.is_outlier)
        self.assertEqual(strong.baseline_mean, 70.0)
        shortlist = pipeline.build_shortlist(self.db, datetime.now(timezone.utc).date())
        self.assertEqual(shortlist[0][1].id, strong.id)
        # Ashok rates the modest one 5 → it becomes a winner and moves the baseline
        pipeline.record_rating(self.db, modest, 5)
        self.db.commit()
        self.assertTrue(modest.exemplar)
        self.assertEqual(rag.baseline(self.db).count, 4)
        pipeline.record_performance(self.db, strong, {'likes': 900, 'comments': 50, 'views': 20000})
        self.db.commit()
        self.assertEqual(strong.status, 'posted')
        self.assertIsNotNone(strong.posted_at)
        self.assertTrue(strong.exemplar)

    def test_scoring_without_ai_keeps_heuristic_capped(self):
        row, _ = pipeline.ingest(self.db, Candidate(text=PERFUME, source='reddit'))
        with mock.patch.object(config, 'AI_REQUIREMENTS_MODE', 'off'):
            pipeline.score_prompt(self.db, row)
        self.assertIsNone(row.ai_score)
        self.assertEqual(row.final_score, 70.0)
        self.assertIsNotNone(row.scored_at)

    def test_exemplars_are_fed_to_the_model(self):
        self.db.add(VideoPrompt(
            fingerprint='win', text=PERFUME, source='manual', collected_at=datetime.now(timezone.utc),
            exemplar=True, final_score=88.0, embedding=rag.hashed_embedding(PERFUME),
        ))
        self.db.commit()
        row, _ = pipeline.ingest(self.db, Candidate(text=COFFEE, source='web'))
        seen: list[str] = []

        def chat(prompt: str) -> str:
            seen.append(prompt)
            return '{"detail": 70, "flow": 70, "reasons": []}'
        pipeline.score_prompt(self.db, row, chat=chat)
        self.assertIn('(88/100)', seen[0])
        self.assertIn('luxury-fragrance', seen[0])


class VideoCreatorTests(unittest.TestCase):
    def test_asset_key_shape_passes_partner_whitelist(self):
        from app.api.partner_assets import _validate_key

        with mock.patch.object(config, 'PROMPT_ASSET_PREFIX', 'prompts'):
            key = video_creator.asset_key('Video', prompt_id=7, suffix='.MP4')
        self.assertTrue(key.startswith('prompts/'))
        self.assertTrue(key.endswith('.mp4'))
        self.assertEqual(_validate_key(key), key)

    def test_create_video_with_fake_replicate_stores_mp4(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / 'product.jpg'
            Image.new('RGB', (64, 64), (0, 200, 120)).save(image)
            captured: dict = {}

            def fake_run(model, input):
                captured['model'] = model
                captured['input'] = input
                return [BytesIO(b'\x00' * 4096)]
            with mock.patch.object(config, 'PARTNER_ASSETS_DIR', tmp), \
                    mock.patch.object(config, 'PARTNER_PUBLIC_BASE_URL', 'https://tower.example'), \
                    mock.patch.object(config, 'REPLICATE_VIDEO_MODEL', 'kwaivgi/kling-v2.1'):
                result = video_creator.create_video(PERFUME, image, prompt_id=3, run=fake_run)
            self.assertEqual(captured['model'], 'kwaivgi/kling-v2.1')
            self.assertEqual(captured['input']['duration'], 10)
            self.assertEqual(captured['input']['prompt'], PERFUME)
            self.assertTrue(result.video_path.is_file())
            self.assertEqual(result.video_path.stat().st_size, 4096)
            self.assertTrue(result.video_url.startswith('https://tower.example/api/partner/v1/assets/prompts/'))
            self.assertEqual((Path(tmp) / '.meta' / result.video_key).read_text(), 'video/mp4')

    def test_empty_output_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / 'p.png'
            Image.new('RGB', (8, 8)).save(image)
            with mock.patch.object(config, 'PARTNER_ASSETS_DIR', tmp):
                with self.assertRaises(RuntimeError):
                    video_creator.create_video('x', image, prompt_id=1, run=lambda m, input: [BytesIO(b'tiny')])

    def test_build_input_branches_per_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / 'p.png'
            Image.new('RGB', (8, 8)).save(image)
            veo = video_creator.build_input('google/veo-3-fast', 'p', image, duration_s=10, aspect_ratio='9:16')
            self.assertIn('image', veo)
            self.assertEqual(veo['aspect_ratio'], '9:16')
            veo['image'].close()
            mini = video_creator.build_input('minimax/video-01', 'p', image, duration_s=6, aspect_ratio='9:16')
            self.assertIn('first_frame_image', mini)
            mini['first_frame_image'].close()


class PostCardTests(unittest.TestCase):
    def test_card_is_vertical_and_uses_category_keyword(self):
        hero = Image.new('RGB', (400, 700), (120, 200, 160))
        card = post_card.render_card(PERFUME, hero=hero, keyword=post_card.keyword_for('perfume', None))
        self.assertEqual(card.size, (1080, 1920))
        self.assertEqual(post_card.keyword_for('perfume', None), 'PERFUME')
        self.assertEqual(post_card.keyword_for(None, 'Sneaker night shot'), 'SNEAKER')
        no_hero = post_card.render_card('short', hero=None, keyword='X')
        self.assertEqual(no_hero.size, (1080, 1920))


if __name__ == '__main__':
    unittest.main()
