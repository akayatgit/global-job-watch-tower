"""Magic-pencil twist: Gemini rewrite + text+image→image stills."""

from __future__ import annotations

import json
import unittest

from app.prompts import reverse_twist
from app.prompts.reverse_prompt import ReferenceFrame


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

    def test_twist_prompt_keeps_original_when_rewrite_is_short(self):
        draft = '[0.0s–8.0s] a juice glass on marble under hard sidelight. ' * 8

        def run(model, input):
            return json.dumps({'keyword': 'X', 'prompt': 'short'})

        self.assertIsNone(reverse_twist.twist_prompt_text(draft, 'make it gold', run=run))

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
        self.assertTrue(all('liquid gold temple' in p for p in seen))
        self.assertIn('0.00s', seen[0])
        self.assertIn('gold pours', seen[0])


class EditImageTests(unittest.TestCase):
    def test_edit_image_sends_image_input_and_prompt(self):
        from app.replicate_img import edit_image

        seen: dict = {}

        def run(model, input):
            seen['model'] = model
            seen['input'] = input
            return b'\xff\xd8' + b'JPEGDATA' + b'\xff\xd9'

        out = edit_image('make it gold', b'\xff\xd8ORIG\xff\xd9', run=run, model='google/nano-banana-2')
        self.assertTrue(out.startswith(b'\xff\xd8'))
        self.assertEqual(seen['input']['prompt'], 'make it gold')
        self.assertEqual(len(seen['input']['image_input']), 1)
        self.assertTrue(seen['input']['image_input'][0].startswith('data:image/jpeg;base64,'))
        self.assertEqual(seen['input']['aspect_ratio'], 'match_input_image')


if __name__ == '__main__':
    unittest.main()
