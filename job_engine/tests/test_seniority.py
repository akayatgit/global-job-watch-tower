"""Fresher truthfulness — title seniority veto (live incident 2026-08-14).

A Deloitte "Omniverse – Software Engineer II" (detail page: Bachelor's +
3–6 years) was shown to guests as "Fresher" because LinkedIn's own
Internship/Entry tag lied and nothing read the title. These tests lock the
veto against the exact live titles plus the false-positive guards.
"""

from __future__ import annotations

import re
import unittest

from app.seniority import (
    EXPLICIT_FRESHER_PATTERN,
    EXPLICIT_FRESHER_REGEX,
    FRESHER_TITLE_REGEX,
    FRESHER_TRACK_SILENCE_LABEL,
    SENIORITY_TITLE_REGEX,
    title_seniority_veto,
)


class TitleSeniorityVetoTests(unittest.TestCase):
    def test_live_incident_titles_are_vetoed(self):
        for title in (
            'Omniverse – Software Engineer II',
            'EH-FY27-Consulting-S&T-M&A-Senior Consultant-IT',
            'Machine Learning-AI and Data Science Engineer II',
        ):
            self.assertTrue(title_seniority_veto(title), title)

    def test_common_seniority_signals_are_vetoed(self):
        for title in (
            'Senior Software Engineer',
            'Sr. Data Analyst',
            'SR Java Developer',
            'Principal Engineer',
            'Staff Software Engineer',
            'Engineering Manager',
            'Assistant Manager - Risk Advisory',
            'Solutions Architect',
            'Head of Data',
            'Director, Product',
            'Vice President - Technology',
            'VP Engineering',
            'Chief Information Security Officer',
            'CTO',
            'Tech Lead',
            'Lead Engineer',
            'Delivery Lead',
            'Cloud Engineer III',
            'Consultant IV',
            'Mid-Senior QA Engineer',
            'Experienced Tax Professional',
            'AI Expert',
        ):
            self.assertTrue(title_seniority_veto(title), title)

    def test_fresher_shaped_titles_are_never_vetoed(self):
        for title in (
            'Software Engineer',
            'Business Resilience - Consultant',
            'Audit Associate',
            'Data Analyst',
            'Software Engineer Intern',
            'Machine Learning Internship',
            'Graduate Engineer Trainee',
            'Management Trainee',
            'Junior Developer',
            'Jr. Python Developer',
            'Apprentice - Data Engineering',
            'Lead Generation Executive',
            'Lead Generation Intern',
        ):
            self.assertFalse(title_seniority_veto(title), title)

    def test_explicit_fresher_wording_defeats_seniority(self):
        # Employer-declared fresher/trainee wording always wins — these are
        # real entry roles even when a seniority-looking token is nearby.
        for title in (
            'Senior Management Trainee',
            'Graduate Trainee - Engineering Lead Program',
            'Intern - Office of the CTO',
        ):
            self.assertFalse(title_seniority_veto(title), title)

    def test_empty_and_none_are_safe(self):
        self.assertFalse(title_seniority_veto(None))
        self.assertFalse(title_seniority_veto(''))
        self.assertFalse(title_seniority_veto('   '))

    def test_patterns_stay_portable_to_postgres(self):
        """The same strings run in Python re and Postgres ~* — no \\b (which
        means backspace in Postgres), no lookbehind, and the (?i) prefix must
        be strippable for ~* (already case-insensitive)."""
        for pattern in (SENIORITY_TITLE_REGEX, FRESHER_TITLE_REGEX):
            self.assertNotIn(r'\b', pattern)
            self.assertNotIn('(?<', pattern)
            self.assertTrue(pattern.startswith('(?i)'))
            re.compile(pattern.removeprefix('(?i)'))

    def test_migration_pattern_matches_live_module(self):
        """The backfill migration froze a copy of these regexes — this pins
        the frozen copy to the module at write time so any later drift is a
        deliberate new migration, never silent divergence."""
        import importlib.util
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[1]
            / 'alembic' / 'versions' / 'b6e4d2c95a10_fresher_title_veto.py'
        )
        spec = importlib.util.spec_from_file_location('fresher_title_veto', path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        self.assertEqual(
            migration.SENIORITY_TITLE_SQL,
            SENIORITY_TITLE_REGEX.removeprefix('(?i)'),
        )
        self.assertEqual(
            migration.FRESHER_TITLE_SQL,
            FRESHER_TITLE_REGEX.removeprefix('(?i)'),
        )


class ExplicitFresherGemTests(unittest.TestCase):
    """/topfreshers gems: only EXPLICIT fresher / 0-experience wording
    qualifies — inference (LinkedIn Entry tag, 'Junior' titles) never does."""

    def test_explicit_wording_matches(self):
        for text in (
            'Data Analyst (Fresher)',
            'Freshers welcome — Software Trainee',
            'Fresh Graduates - 2026 batch',
            'No prior experience required',
            'No experience needed, we train you',
            'Zero experience? Apply now',
            '0 years of experience',
            '0-2 years experience',
            '0 to 2 yrs',
            '0+ years',
            'Experience: 0 – 1 years',
        ):
            self.assertTrue(EXPLICIT_FRESHER_PATTERN.search(text), text)

    def test_inference_and_lookalikes_never_match(self):
        for text in (
            'Junior Software Engineer',       # early-career, but not explicit
            'Graduate Engineer Trainee',      # fresher-adjacent, not explicit
            'Internship — Data Science',
            '10 years of experience',         # the 0 must not match inside 10
            'Minimum 5 Year(s) Of Experience Is Required',
            'Refresher training provided',    # 'refresher' is not 'fresher'
            'Entry level',                    # LinkedIn's tag, not a statement
        ):
            self.assertFalse(EXPLICIT_FRESHER_PATTERN.search(text), text)

    def test_pattern_stays_portable_to_postgres(self):
        self.assertNotIn(r'\b', EXPLICIT_FRESHER_REGEX)
        self.assertNotIn('(?<', EXPLICIT_FRESHER_REGEX)
        self.assertTrue(EXPLICIT_FRESHER_REGEX.startswith('(?i)'))
        re.compile(EXPLICIT_FRESHER_REGEX.removeprefix('(?i)'))

    def test_silence_stamp_label_matches_tasks_and_is_excluded_from_clause(self):
        """card_requirements stamps this exact label from LinkedIn's f_E=1,2
        silence — the explicit-fresher clause must name (and exclude) the
        same string, so pin them together."""
        from app.tasks import card_requirements

        _req, band, label = card_requirements('Plain card text', 'fresher', title='Data Analyst')
        self.assertEqual(band, 'Fresher')
        self.assertEqual(label, FRESHER_TRACK_SILENCE_LABEL)

    def test_clause_covers_title_details_stated_years_and_label(self):
        from app.seniority import explicit_fresher_clause

        sql = str(explicit_fresher_clause().compile(compile_kwargs={'literal_binds': True}))
        self.assertIn('title', sql)
        self.assertIn('raw_text', sql)
        self.assertIn('experience_min_years', sql)
        self.assertIn('experience_label', sql)
        self.assertIn(FRESHER_TRACK_SILENCE_LABEL, sql)


if __name__ == '__main__':
    unittest.main()
