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


if __name__ == '__main__':
    unittest.main()
