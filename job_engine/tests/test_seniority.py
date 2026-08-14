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
    FRESHER_TITLE_REGEX,
    FRESHER_TRACK_SILENCE_LABEL,
    MANDATORY_FRESHER_TITLE_PATTERN,
    MANDATORY_FRESHER_TITLE_REGEX,
    SENIORITY_TITLE_REGEX,
    is_mandatory_fresher,
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


class MandatoryFresherLawTests(unittest.TestCase):
    """The mandatory fresher law (Ashok, 2026-08-14 21:02): a servable job
    must literally say fresher in the TITLE or state 0–1 years of experience.
    Stated years above 1 veto everything — card marketing, labels, and
    LinkedIn's Entry tag are never evidence. This killed the 9/10 bad
    /topfreshers list."""

    def test_stated_0_to_1_years_qualifies_regardless_of_title(self):
        for title, min_years in (
            ('Data Platform Engineer', 0.0),
            ('SQL Developer', 1.0),
            ('Software Engineer', 0.5),
            (None, 0.0),
        ):
            self.assertTrue(is_mandatory_fresher(title, min_years), (title, min_years))

    def test_stated_years_above_1_veto_everything(self):
        # The exact live failure: card/details shouting "Freshers" while the
        # detail page states real years. Stated years always win.
        for title, min_years in (
            ('Data Analyst (Fresher)', 3.0),
            ('Freshers welcome — SQL Developer', 5.0),
            ('Software Engineer', 2.0),
            ('Fresh Graduate Program', 1.5),
        ):
            self.assertFalse(is_mandatory_fresher(title, min_years), (title, min_years))

    def test_without_stated_years_only_fresher_in_title_qualifies(self):
        for title in (
            'Data Analyst (Fresher)',
            'Freshers — Software Trainee',
            'Fresh Graduate Hiring 2026',
        ):
            self.assertTrue(is_mandatory_fresher(title, None), title)
        for title in (
            'Junior Software Engineer',       # early-career, not explicit
            'Graduate Engineer Trainee',      # fresher-adjacent, not explicit
            'Internship — Data Science',
            'Refresher training provided',    # 'refresher' is not 'fresher'
            'Data Platform Engineer',
            'Entry Level Software Engineer',  # LinkedIn vocabulary, not a statement
            '',
            None,
        ):
            self.assertFalse(is_mandatory_fresher(title, None), title)

    def test_title_pattern_matches_only_fresher_words(self):
        self.assertTrue(MANDATORY_FRESHER_TITLE_PATTERN.search('Fresher'))
        self.assertTrue(MANDATORY_FRESHER_TITLE_PATTERN.search('freshers batch'))
        self.assertTrue(MANDATORY_FRESHER_TITLE_PATTERN.search('Fresh Graduates 2026'))
        self.assertFalse(MANDATORY_FRESHER_TITLE_PATTERN.search('Refresher course'))
        self.assertFalse(MANDATORY_FRESHER_TITLE_PATTERN.search('Fresh produce buyer'))

    def test_pattern_stays_portable_to_postgres(self):
        self.assertNotIn(r'\b', MANDATORY_FRESHER_TITLE_REGEX)
        self.assertNotIn('(?<', MANDATORY_FRESHER_TITLE_REGEX)
        self.assertTrue(MANDATORY_FRESHER_TITLE_REGEX.startswith('(?i)'))
        re.compile(MANDATORY_FRESHER_TITLE_REGEX.removeprefix('(?i)'))

    def test_silence_stamp_label_is_pinned_to_tasks(self):
        """card_requirements still stamps this label from LinkedIn's f_E=1,2
        silence — kept pinned so the serving law can keep ignoring it."""
        from app.tasks import card_requirements

        _req, band, label = card_requirements('Plain card text', 'fresher', title='Data Analyst')
        self.assertEqual(band, 'Fresher')
        self.assertEqual(label, FRESHER_TRACK_SILENCE_LABEL)

    def test_clause_matches_the_python_twin_shape(self):
        from app.seniority import mandatory_fresher_clause

        sql = str(mandatory_fresher_clause().compile(compile_kwargs={'literal_binds': True}))
        self.assertIn('experience_min_years', sql)
        self.assertIn('title', sql)
        # No loose evidence sources may creep back in.
        self.assertNotIn('raw_text', sql)
        self.assertNotIn('experience_label', sql)


if __name__ == '__main__':
    unittest.main()
