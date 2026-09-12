"""Magic-pencil twist: Gemini rewrite + text+image→image stills."""

from __future__ import annotations

import io
import json
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from app import config
from app.prompts import reverse_twist
from app.prompts.reverse_prompt import ReferenceFrame
from app.prompts.video_creator import RenderResult


class TwistUnitTests(unittest.TestCase):
    def test_segment_for_time_picks_the_covering_beat(self):
        prompt = (
            '[0.0s–1.8s] a glass on marble.\n'
            '[1.8s–4.0s] a hand pours gold.\n'
            'Style: midnight temple.'
        )
        self.assertIn('hand pours gold', reverse_twist.segment_for_time(prompt, 2.5))
        self.assertIn('glass on marble', reverse_twist.segment_for_time(prompt, 0.2))

    def test_twist_prompt_sends_draft_and_twist_to_gemini(self):
        draft = '[0.0s–8.0s] a juice glass on marble under hard sidelight. Style: cold. ' * 6
        seen: dict = {}

        def run(model, input):
            seen['input'] = input
            seen['model'] = model
            return json.dumps({
                'keyword': 'GOLD',
                'prompt': '[0.0s–8.0s] ' + (
                    'liquid gold climbs the glass in a midnight temple, slow-mo pour, sacred hush. '
                    * 10
                ) + 'Style: mythic commercial.',
                'cuts': [{'start': 0.0, 'end': 8.0}],
            })

        reading = reverse_twist.twist_prompt_text(
            draft, 'the drink becomes liquid gold in a midnight temple', run=run,
        )
        self.assertIsNotNone(reading)
        self.assertEqual(reading.keyword, 'GOLD')
        self.assertIn('liquid gold', reading.prompt)
        self.assertNotIn('videos', seen['input'])
        self.assertNotIn('images', seen['input'])
        self.assertIn('liquid gold in a midnight temple', seen['input']['prompt'])
        self.assertIn(draft[:40], seen['input']['prompt'])
        self.assertIn('every timestamped segment', seen['input']['system_instruction'].lower())
        self.assertIn('under 3000', seen['input']['system_instruction'])
        self.assertGreater(seen['input']['thinking_budget'], 0)

    def test_twist_prompt_falls_back_when_rewrite_is_short(self):
        draft = '[0.0s–8.0s] a juice glass on marble under hard sidelight. ' * 8

        def run(model, input):
            return json.dumps({'keyword': 'X', 'prompt': 'short'})

        reading = reverse_twist.twist_prompt_text(draft, 'make it gold', run=run)
        self.assertIsNotNone(reading)
        self.assertIn('[0.0s–8.0s]', reading.prompt)
        self.assertIn('juice glass', reading.prompt)
        self.assertIn('gold', reading.prompt.lower())
        self.assertIn('fallback', reading.model)

    def test_twist_prompt_falls_back_when_gemini_errors(self):
        draft = '[0.0s–1.8s] a glass on marble.\n[1.8s–4.0s] a hand pours.\nStyle: cold.'

        def run(model, input):
            raise RuntimeError('E001')

        notes: list[str] = []
        reading = reverse_twist.twist_prompt_text(
            draft, 'Eiffel tower assembly', run=run, log=notes.append,
        )
        self.assertIsNotNone(reading)
        self.assertIn('Eiffel tower assembly', reading.prompt)
        self.assertIn('glass on marble', reading.prompt)
        self.assertTrue(any('fallback' in n.lower() or 'missed' in n.lower() for n in notes))

    def test_fallback_stamps_twist_on_every_beat(self):
        draft = '[0.0s–1.8s] a glass on marble.\n[1.8s–4.0s] a hand pours.\nStyle: midnight.'
        text = reverse_twist.fallback_twist_prompt(draft, 'Eiffel tower')
        self.assertIn('[0.0s–1.8s]', text)
        self.assertIn('[1.8s–4.0s]', text)
        self.assertEqual(text.lower().count('eiffel tower'), 3)

    def test_twist_prompt_stays_strictly_under_3000(self):
        draft = '[0.0s–8.0s] a juice glass on marble under hard sidelight. Style: cold. ' * 6
        long_prompt = (
            '[0.0s–8.0s] ' + ('liquid gold climbs the glass in a midnight temple. ' * 80)
            + '\nStyle: mythic commercial.'
        )
        self.assertGreaterEqual(len(long_prompt), 3000)

        def run(model, input):
            return json.dumps({
                'keyword': 'GOLD',
                'prompt': long_prompt,
                'cuts': [{'start': 0.0, 'end': 8.0}],
            })

        reading = reverse_twist.twist_prompt_text(draft, 'make it gold', run=run)
        self.assertIsNotNone(reading)
        self.assertLess(len(reading.prompt), 3000)
        self.assertIn('[0.0s–8.0s]', reading.prompt)

    def test_twist_frames_edit_each_jpeg_and_rename(self):
        frames = [
            ReferenceFrame(t=0.0, key='k0', filename='cut-01-0.00s.jpg'),
            ReferenceFrame(t=1.76, key='k1', filename='cut-02-1.76s.jpg'),
        ]
        stored: list[tuple[str, bytes]] = []
        seen: list[str] = []

        def edit(prompt, image, **_k):
            seen.append(prompt)
            return b'JPEG-' + image + (b'X' * 80)

        out, failed = reverse_twist.twist_reference_frames(
            frames,
            twist='liquid gold temple',
            twisted_prompt='[0.0s–8.0s] gold pours from a temple spout.',
            prompt_id=11,
            read_asset=lambda key: b'ORIG-' + key.encode() + (b'Y' * 80),
            edit=edit,
            store=lambda key, data, content_type=None: stored.append((key, data)),
            key_for=lambda kind, prompt_id, suffix: f'prompts/d/{kind}-{prompt_id}.{suffix}',
        )
        self.assertEqual(failed, [])
        self.assertEqual([f.filename for f in out], ['twist-01-0.00s.jpg', 'twist-02-1.76s.jpg'])
        self.assertEqual(len(stored), 2)
        expected = reverse_twist.frame_edit_prompt('liquid gold temple')
        self.assertTrue(expected.startswith('Change from the source frame to '))
        self.assertIn(', and keep pose, lighting, details and identity', expected)
        self.assertEqual(seen, [expected, expected])
        self.assertNotIn('IDENTITY LOCK', expected)
        self.assertNotIn('gold pours', expected)

    def test_omni_attempts_send_source_video_and_twisted_stills(self):
        attempts = reverse_twist.omni_input_attempts(
            prompt='Motion transfer. Twist: gold.',
            video_url='https://tower.example/clip.mp4',
            frame_urls=[
                'https://tower.example/a.jpg',
                'https://tower.example/b.jpg',
            ],
        )
        first = attempts[0]
        self.assertEqual(first['video'], 'https://tower.example/clip.mp4')
        self.assertEqual(first['image'], 'https://tower.example/a.jpg')
        self.assertEqual(first['last_frame'], 'https://tower.example/b.jpg')
        self.assertEqual(first['task'], 'edit')
        self.assertEqual(first['resolution'], '720p')
        self.assertEqual(first['aspect_ratio'], '9:16')
        self.assertTrue(any('task' not in item and 'video' in item for item in attempts))
        self.assertTrue(any('video' not in item and item.get('image') for item in attempts))

    def test_render_twist_video_stores_omni_mp4(self):
        seen: list[dict] = []

        def run(model, input):
            seen.append({'model': model, 'input': input})
            return b'X' * 2048

        frames = [ReferenceFrame(t=0.0, key='prompts/d/tw.jpg', filename='twist-01.jpg')]
        stored: list[tuple[str, bytes]] = []
        with mock.patch.object(config, 'PROMPT_TWIST_VIDEO_MODEL', 'google/gemini-omni-1.1'), \
                mock.patch.object(config, 'PARTNER_PUBLIC_BASE_URL', 'https://tower.example'):
            result = reverse_twist.render_twist_video(
                twist='liquid gold temple',
                twisted_prompt='[0.0s–8.0s] gold pours from a temple spout.',
                frames=frames,
                video_url='https://tower.example/api/partner/v1/assets/prompts/d/src.mp4?download=1',
                duration_s=8.0,
                prompt_id=11,
                run=run,
                store=lambda key, data, content_type=None: stored.append((key, data)) or Path(key),
                key_for=lambda kind, prompt_id, suffix: f'prompts/d/{kind}-{prompt_id}.{suffix}',
                read_output=lambda output: output,
            )
        self.assertIsInstance(result, RenderResult)
        self.assertEqual(result.model, 'google/gemini-omni-1.1')
        self.assertEqual(stored[0][0], 'prompts/d/twvid-11.mp4')
        self.assertEqual(len(stored[0][1]), 2048)
        self.assertEqual(seen[0]['model'], 'google/gemini-omni-1.1')
        self.assertEqual(
            seen[0]['input']['video'],
            'https://tower.example/api/partner/v1/assets/prompts/d/src.mp4',
        )
        self.assertEqual(seen[0]['input']['image'], 'https://tower.example/api/partner/v1/assets/prompts/d/tw.jpg')
        self.assertIn('liquid gold temple', seen[0]['input']['prompt'])

    def test_pack_frames_zip_is_one_downloadable_archive(self):
        frames = [
            {'t': 0.0, 'key': 'k0', 'filename': 'cut-01-0.00s.jpg'},
            {'t': 1.7, 'key': 'k1', 'filename': 'cut-02-1.70s.jpg'},
            {'t': 2.0, 'key': '', 'filename': 'cut-03.jpg'},
        ]
        data, failed = reverse_twist.pack_frames_zip(
            frames, fetch=lambda key: b'JPEG-' + key.encode(),
        )
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        self.assertEqual(names, ['cut-01-0.00s.jpg', 'cut-02-1.70s.jpg'])
        self.assertEqual(failed, ['3'])


class EditImageTests(unittest.TestCase):
    def test_edit_image_sends_image_input_and_prompt(self):
        from app.replicate_img import edit_image

        seen: dict = {}

        def run(model, input):
            seen['model'] = model
            seen['input'] = input
            return b'\xff\xd8' + b'JPEGDATA' + b'\xff\xd9'

        with mock.patch.object(config, 'PROMPT_TWIST_IMAGE_MODEL', ''):
            out = edit_image('Change from x to y, and z', b'\xff\xd8ORIG\xff\xd9', run=run)
        self.assertTrue(out.startswith(b'\xff\xd8'))
        self.assertEqual(seen['model'], 'google/nano-banana-2-lite')
        self.assertEqual(seen['input']['prompt'], 'Change from x to y, and z')
        self.assertEqual(len(seen['input']['image_input']), 1)
        self.assertTrue(seen['input']['image_input'][0].startswith('data:image/jpeg;base64,'))
        self.assertEqual(seen['input']['aspect_ratio'], 'match_input_image')
        self.assertEqual(seen['input']['resolution'], '1K')
        self.assertNotIn('google_search', seen['input'])
        hd = edit_image(
            'Change from x to y, and z',
            b'\xff\xd8ORIG\xff\xd9',
            run=run,
            model='google/nano-banana-2',
        )
        self.assertTrue(hd.startswith(b'\xff\xd8'))
        self.assertEqual(seen['model'], 'google/nano-banana-2')
        self.assertEqual(seen['input']['resolution'], '2K')
        pro = edit_image(
            'Change from x to y, and z',
            b'\xff\xd8ORIG\xff\xd9',
            run=run,
            model='google/nano-banana-pro',
        )
        self.assertTrue(pro.startswith(b'\xff\xd8'))
        self.assertEqual(seen['input']['resolution'], '2K')


if __name__ == '__main__':
    unittest.main()
