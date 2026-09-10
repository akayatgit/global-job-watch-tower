"""Prompt Tower core (pivot 2026-09-09): normalize → sources → RAG →
Hermes scoring → daily top-10 → feedback learning → video creator/card.

Everything runs offline: sqlite in-memory, a fake model, a fake Replicate.
"""

from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest import mock
import html

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
# Cinematic, camera-rich — and not a product video. Stored on 2026-09-10 by
# the old product-or-motion gate; the samurai must never read as a prompt.
SAMURAI = (
    'A lone samurai stands on a windswept cliff at golden hour, cherry blossoms drifting '
    'through the frame. Slow dolly push-in on a 50 mm lens, shallow depth of field, rim light '
    'catching the edge of the blade, long shadows across the wet rock. He slowly draws the sword, '
    'the camera tilts up to the storm clouds, 24 fps, cinematic 16:9, photorealistic, 4K render. '
    'Rain begins to fall, each droplet glinting in the backlight as the scene settles into silence.'
)
TEMPLATE = (
    'Create a [duration]-second [aspect ratio] product ad for [product] by [brand]. '
    'Camera: [camera movement] on a [lens] lens with shallow depth of field. Lighting: [lighting style] '
    'with soft rim light and gentle reflections on the glass bottle. Motion: the product slowly rotates '
    'and floats above [surface]. Keep the logo and packaging exact, photorealistic, 4K, 30 fps.'
)
PROSE = (
    'How does each block change the output? Camera is the block most beginners under-use and the one '
    'Google ranks first in its own guide. If you leave lighting out, the model usually picks flat studio '
    'light for a product shot; if you state golden hour and a rim light on the bottle, the render follows. '
    'A strong prompt is specific enough to protect the product and flexible enough to let Veo 3 produce motion.'
)


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

    def test_title_drops_the_whole_article_after_create(self):
        self.assertEqual(
            normalize.make_title('Create an 8-second calm product page video for a desk vacuum. Show it.', 'tech'),
            '8-second calm product page video for a desk vacuum',
        )
        self.assertEqual(normalize.make_title('Create a 6-second ad. More.', None), '6-second ad')
        self.assertEqual(normalize.make_title('Generate the hero shot. Then.', None), 'Hero shot')
        self.assertEqual(normalize.make_title('Create amber candle macro. x', None), 'Amber candle macro')

    def test_gate_requires_a_product_as_a_whole_word(self):
        reading = normalize.read_prompt(SAMURAI)
        self.assertFalse(reading.is_prompt)
        self.assertIn('no product — not a D2C video prompt', reading.reasons)
        # substring matches that fooled the old gate: 'can' in candle/scan, 'ad' in shadow
        self.assertEqual(normalize.product_word_hits('long shadows, a wide scan of the stadium'), 0)
        self.assertEqual(normalize.product_word_hits('the perfume bottle and its cap'), 2)
        for text in (PERFUME, COFFEE, SNEAKER):
            self.assertTrue(normalize.read_prompt(text).is_prompt, text[:40])

    def test_fill_in_template_is_not_a_finished_prompt(self):
        reading = normalize.read_prompt(TEMPLATE)
        self.assertFalse(reading.is_prompt)
        self.assertIn('fill-in template, not a finished prompt', reading.reasons)
        # one or two slots ("[brand]") are how public handbooks anonymise — allowed
        self.assertTrue(normalize.read_prompt(PERFUME.replace('luxury-fragrance', '[brand] fragrance')).is_prompt)

    def test_non_english_index_page_is_rejected(self):
        cjk = '产品视频提示词 ' * 30 + COFFEE
        self.assertGreater(normalize.cjk_ratio(cjk), normalize.MAX_CJK_RATIO)
        self.assertFalse(normalize.read_prompt(cjk).is_prompt)
        self.assertEqual(normalize.cjk_ratio(COFFEE), 0.0)

    def test_explainer_prose_about_prompting_is_rejected(self):
        reading = normalize.read_prompt(PROSE)
        self.assertFalse(reading.is_prompt)
        self.assertIn('explainer prose about prompting, not a prompt', reading.reasons)
        self.assertTrue(normalize.looks_like_prose('Use this when the product is visually attractive: skincare, jewelry.'))
        self.assertTrue(normalize.looks_like_prose('0-2s: Hook — a visual interruption. 2-7s: Demo — show the product.'))
        self.assertTrue(normalize.looks_like_prose('Want these turned into finished ad videos? Try HeyDreaming.'))
        # Real prompts survive: constraint words, "model" as a person, a name-dropped tool
        self.assertFalse(normalize.looks_like_prose(PERFUME))
        self.assertFalse(normalize.looks_like_prose(
            'A model holds the serum bottle to the light; the camera should orbit slowly and avoid '
            'harsh shadows. Notes of vanilla drift as text. Made for Veo 3.'
        ))
        self.assertTrue(normalize.read_prompt(f'Here is my Veo 3 prompt: {COFFEE}').is_prompt)

    def test_strip_markdown_drops_readme_chrome_and_keeps_slots(self):
        raw = (
            '## Product Showcase\n'
            '- [Candle explainer](#candle) | - [UGC](#ugc)\n'
            '`6s · 9:16` · `skincare`\n'
            '| Model | Notes |\n'
            '⬆ [Back to top](#top)\n'
            '> 💡 Tip: swap the brand\n'
            '**Premium** feature explainer for a [brand] soy candle, see [the guide](https://x.y/z).\n'
        )
        text = normalize.strip_markdown(raw)
        self.assertNotIn('Product Showcase', text)
        self.assertNotIn('Back to top', text)
        self.assertNotIn('| Model', text)
        self.assertNotIn('💡', text)
        self.assertIn('Premium feature explainer for a [brand] soy candle, see the guide.', text)
        self.assertNotIn('https://', text)


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

    def test_reddit_rss_fallback_when_json_blocked(self):
        rss = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            '<entry>'
            '<title>LV perfume ad recreated</title>'
            '<link href="https://www.reddit.com/r/aivideo/comments/abc/lv/"/>'
            '<author><name>/u/promptsmith</name></author>'
            f'<content type="html">{html.escape(f"<pre><code>{PERFUME}</code></pre>")}</content>'
            '</entry></feed>'
        )

        def fetch(url: str) -> str:
            if 'new.json' in url:
                raise OSError('HTTP Error 403: Blocked')
            if url.endswith('.rss'):
                return rss
            raise AssertionError(url)

        paused: list[float] = []
        out = sources.reddit_candidates(['aivideo'], fetch=fetch, pause_s=8, pause=paused.append)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].source, 'reddit')
        self.assertEqual(out[0].author, 'promptsmith')
        self.assertEqual(out[0].source_url, 'https://www.reddit.com/r/aivideo/comments/abc/lv/')
        self.assertIn('Preserve the exact', out[0].text)
        # A failed JSON call breathes (capped at 3s) before the RSS retry
        self.assertEqual(paused, [3.0])

    def test_reddit_paces_subs_and_403_switches_to_rss_only(self):
        calls: list[str] = []
        paused: list[float] = []

        def fetch(url: str) -> str:
            calls.append(url)
            if 'new.json' in url:
                raise urllib.error.HTTPError(url, 403, 'Blocked', hdrs=None, fp=None)
            return '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'

        reports: list[sources.SourceReport] = []
        out = sources.reddit_candidates(
            ['aivideo', 'VeoAI', 'KlingAI'], fetch=fetch, reports=reports,
            pause_s=8, pause=paused.append,
        )
        self.assertEqual(out, [])
        # JSON tried once, then RSS-only for the remaining subs
        self.assertEqual(sum('new.json' in u for u in calls), 1)
        self.assertEqual(sum(u.endswith('.rss') for u in calls), 3)
        # 8s between subs (twice), 3s breather after the failed JSON call
        self.assertEqual(paused, [3.0, 8, 8])
        self.assertEqual(len(reports), 3)

    def test_reddit_sub_names_keep_their_leading_letters(self):
        calls: list[str] = []

        def fetch(url: str) -> str:
            calls.append(url)
            return json.dumps({'data': {'children': []}})

        sources.reddit_candidates(['runwayml', 'r/aivideo', '/r/Sora/'], fetch=fetch, pause_s=0, pause=lambda _s: None)
        subs = [c.split('/r/')[1].split('/')[0] for c in calls if 'new.json' in c]
        self.assertEqual(subs, ['runwayml', 'aivideo', 'Sora'])

    def test_reddit_429_stops_touching_reddit_for_the_run(self):
        calls: list[str] = []

        def fetch(url: str) -> str:
            calls.append(url)
            raise urllib.error.HTTPError(url, 429, 'Too Many Requests', hdrs=None, fp=None)

        reports: list[sources.SourceReport] = []
        out = sources.reddit_candidates(
            ['aivideo', 'VeoAI', 'KlingAI'], fetch=fetch, reports=reports,
            pause_s=0, pause=lambda _s: None,
        )
        self.assertEqual(out, [])
        self.assertEqual(len(calls), 1)  # first JSON call 429s, nothing else is fetched
        self.assertEqual(len(reports), 3)
        self.assertIn('429', reports[0].error)
        self.assertTrue(all(r.error.startswith('skipped') for r in reports[1:]))

    def test_web_page_pre_blocks_and_body_paragraphs(self):
        page = f'<html><body><h1>Prompts</h1><pre>{PERFUME}</pre><p>{CAPTION}</p><p>{COFFEE}</p></body></html>'
        out = sources.web_candidates(['https://promptbase.com/x'], fetch=lambda url: page)
        texts = [c.text for c in out]
        self.assertEqual(len(out), 2)
        self.assertTrue(all(c.source == 'promptbase' for c in out))
        self.assertTrue(any('fragrance' in t for t in texts))
        self.assertTrue(any('cold brew' in t for t in texts))

    def test_readme_toc_and_cjk_headers_never_merge_into_a_prompt(self):
        readme = (
            '# Awesome Ad Video Prompts\n\n'
            '- Product Showcase (6) | - UGC & Authentic (6) | - Before & After (4)\n'
            '- Unboxing (3) | - Lifestyle (5)\n\n'
            '产品展示 · 开箱 · 生活方式\n\n'
            f'{PERFUME}\n\n'
            '`10s · 9:16` · `perfume`\n\n'
            f'{COFFEE}\n'
        )
        blocks = sources.extract_prompt_blocks(readme)
        self.assertEqual(len(blocks), 2)
        self.assertTrue(blocks[0].startswith('Create a 10-second'))
        self.assertTrue(blocks[1].startswith('A 8-second'))
        self.assertTrue(sources._is_chrome_paragraph('- Product Showcase (6) | - UGC (6)\n- Unboxing (3)'))
        self.assertTrue(sources._is_chrome_paragraph('产品展示 · 开箱 · 生活方式'))
        self.assertFalse(sources._is_chrome_paragraph(COFFEE))

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
                if 'new.json' in url:
                    return json.dumps({'data': {'children': []}})
                if url.endswith('.rss'):
                    return '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
                return f'<pre>{SNEAKER}</pre>'
            out = sources.gather_candidates(fetch=fetch)
        self.assertEqual(len(out), 1)
        self.assertTrue(any('new.json' in url for url in calls))
        self.assertTrue(any(url.endswith('.rss') for url in calls))
        self.assertTrue(any('example.com' in url for url in calls))


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

    def test_run_daily_records_a_prompt_scan_event(self):
        from app.models import TowerEvent
        pipeline.run_daily(
            self.db, day=date(2026, 9, 10),
            candidates=[Candidate(text=PERFUME, source='web')],
            chat=fake_chat_factory(),
        )
        kinds = [row.kind for row in self.db.query(TowerEvent).all()]
        self.assertIn('prompt_scan', kinds)

    def test_reaudit_rejects_stored_non_product_rows_and_rebuilds_shortlist(self):
        day = date(2026, 9, 10)
        # Simulate the pre-product-gate catalogue: the samurai slipped in and got shortlisted.
        stored = pipeline.ingest(self.db, Candidate(text=PERFUME, source='web'))[0]
        samurai = VideoPrompt(
            text=SAMURAI, fingerprint=normalize.fingerprint(SAMURAI), source='web',
            status='shortlisted', heuristic_score=70.0, title='Samurai cliff',
        )
        self.db.add(samurai)
        self.db.commit()
        self.db.add_all([
            PromptShortlist(day=day, rank=1, prompt_id=samurai.id),
            PromptShortlist(day=day, rank=2, prompt_id=stored.id),
        ])
        self.db.commit()

        rejected, touched = pipeline.reaudit_stored(self.db)
        self.assertEqual(rejected, 1)
        self.assertEqual(touched, {day})
        self.db.refresh(samurai)
        self.assertEqual(samurai.status, 'rejected')
        self.assertEqual([e.prompt_id for e in self.db.query(PromptShortlist).all()], [stored.id])

        # run_daily on that day re-audits and rebuilds the shortlist without the samurai
        summary = pipeline.run_daily(
            self.db, day=day, candidates=[Candidate(text=COFFEE, source='web')], chat=fake_chat_factory(),
        )
        self.assertEqual(summary['reaudited'], 0)
        ids = {p.id for _e, p in pipeline.shortlist_for_day(self.db, day)}
        self.assertNotIn(samurai.id, ids)
        self.assertIn(stored.id, ids)

    def test_idle_scan_reason_kicks_empty_and_stale_but_not_a_fresh_retry(self):
        now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(
            pipeline.idle_scan_reason(
                prompt_count=0, last_collected_at=None, last_scan_at=None, now=now,
            ),
            'empty-catalogue',
        )
        self.assertIsNone(
            pipeline.idle_scan_reason(
                prompt_count=0,
                last_collected_at=None,
                last_scan_at=now - timedelta(minutes=5),
                now=now,
            ),
        )
        self.assertEqual(
            pipeline.idle_scan_reason(
                prompt_count=4,
                last_collected_at=now - timedelta(hours=7),
                last_scan_at=now - timedelta(hours=7),
                now=now,
            ),
            'stale-catalogue',
        )
        self.assertIsNone(
            pipeline.idle_scan_reason(
                prompt_count=4,
                last_collected_at=now - timedelta(hours=1),
                last_scan_at=now - timedelta(hours=1),
                now=now,
            ),
        )

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
        # Deck of 4 with 6 eligible rows: the origin cap decides who is in
        shortlist = pipeline.build_shortlist(self.db, datetime.now(timezone.utc).date(), size=4)
        sources_used = [p.source for _e, p in shortlist]
        self.assertEqual(sources_used.count('reddit'), 3)
        self.assertIn('manual', sources_used)
        self.assertNotIn('web', sources_used)  # below PROMPT_MIN_SCORE

    def test_shortlist_fills_a_thin_day_after_the_diversity_pass(self):
        day = datetime.now(timezone.utc).date()
        for i in range(1, 6):
            text = f'{SNEAKER} Variation {i}: extra {"detail " * i}shot of the {i} mm lens.'
            self.db.add(VideoPrompt(
                fingerprint=normalize.fingerprint(text), text=text, source='web',
                source_url='https://raw.githubusercontent.com/x/y/README.md',
                collected_at=datetime.now(timezone.utc), heuristic_score=90.0,
                final_score=80.0 - i, scored_at=datetime.now(timezone.utc), status='new',
            ))
        for i in range(1, 3):
            text = f'{COFFEE} Variant {i}.'
            self.db.add(VideoPrompt(
                fingerprint=normalize.fingerprint(text), text=text, source='web',
                source_url='https://www.veo3ai.io/blog/post',
                collected_at=datetime.now(timezone.utc), heuristic_score=90.0,
                final_score=60.0, scored_at=datetime.now(timezone.utc), status='new',
            ))
        self.db.commit()
        shortlist = pipeline.build_shortlist(self.db, day, size=10)
        # All seven eligible rows make the deck (5 github + 2 veo3ai) — the
        # cap picks first, then leftovers fill; order is by score.
        self.assertEqual(len(shortlist), 7)
        scores = [p.final_score for _e, p in shortlist]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual([e.rank for e, _p in shortlist], list(range(1, 8)))
        # With only 6 slots the cap bites: 3 github + 2 veo3ai + best leftover github
        rebuilt = pipeline.build_shortlist(self.db, day, size=6, force=True)
        origins = [pipeline.prompt_origin(p) for _e, p in rebuilt]
        self.assertEqual(origins.count('web:raw.githubusercontent.com'), 4)
        self.assertEqual(origins.count('web:www.veo3ai.io'), 2)

    def test_prompt_origin_is_subreddit_or_page_host(self):
        self.assertEqual(
            pipeline.prompt_origin(VideoPrompt(source='reddit', source_url='https://www.reddit.com/r/VeoAI/comments/x/y/')),
            'reddit:veoai',
        )
        self.assertEqual(
            pipeline.prompt_origin(VideoPrompt(source='web', source_url='https://prompt-architects.com/blog/p')),
            'web:prompt-architects.com',
        )
        self.assertEqual(pipeline.prompt_origin(VideoPrompt(source='manual', source_url=None)), 'manual')
        self.assertEqual(pipeline.prompt_origin(VideoPrompt(source='reddit', source_url=None)), 'reddit')

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


class IdleKickTests(unittest.TestCase):
    def test_empty_catalogue_dispatches_prompt_scan(self):
        from app import tasks

        db = make_session()

        class _Ctx:
            def __enter__(self):
                return db

            def __exit__(self, *args):
                return False

        with mock.patch.object(tasks, 'SessionLocal', lambda: _Ctx()), \
                mock.patch.object(tasks, 'daily_prompt_pipeline') as pipe, \
                mock.patch.object(tasks, 'console_log'):
            result = tasks._maybe_dispatch_idle_prompt_scan()
        self.assertTrue(result['kicked'])
        self.assertEqual(result['reason'], 'empty-catalogue')
        pipe.delay.assert_called_once()


if __name__ == '__main__':
    unittest.main()
