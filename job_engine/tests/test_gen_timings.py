"""Per-step generation clocks — one Telegram line, no invented totals."""

from __future__ import annotations

import json
import unittest

from app.prompts.gen_timings import Clock, format_line, load_marks


class GenTimingsTests(unittest.TestCase):
    def test_format_line_shows_total_and_named_steps(self):
        line = format_line({
            'started_at': '2026-09-12T14:00:00+00:00',
            'total': 121,
            'download': 18,
            'describe': 70,
            'reel': 8,
        })
        self.assertEqual(line, '⏱ 2m 01s · download 18s · describe 1m 10s · reel 8.0s')

    def test_format_line_empty_marks_is_blank(self):
        self.assertEqual(format_line(None), '')
        self.assertEqual(format_line({'started_at': '2026-09-12T14:00:00+00:00'}), '')

    def test_clock_snapshot_has_no_total_until_finish(self):
        clock = Clock()
        clock.start('download')
        clock.stop('download')
        snap = load_marks(clock.snapshot())
        self.assertIn('started_at', snap)
        self.assertIn('download', snap)
        self.assertNotIn('total', snap)
        finished = json.loads(clock.dumps())
        self.assertIn('total', finished)
        self.assertIn('finished_at', finished)

    def test_second_finish_records_twist_total(self):
        clock = Clock({'total': 90, 'started_at': '2026-09-12T14:00:00+00:00', 'omni': 12.4})
        marks = clock.finish()
        self.assertEqual(marks['total'], 90)
        self.assertIn('twist_total', marks)
        line = format_line({**marks, 'twist_total': 20})
        self.assertIn('omni 12s', line)
        self.assertIn('twist_total 20s', line)


if __name__ == '__main__':
    unittest.main()
