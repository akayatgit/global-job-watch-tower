"""Tests for GTM target-role allowlist + collection-city gate."""

from __future__ import annotations

import unittest

from app.cities import (
    COLLECTION_CITY_KEYS,
    is_collection_city,
    normalize_city,
    parse_city_filter_list,
)
from app.target_roles import title_matches_target_role


class TargetRoleAllowlistTests(unittest.TestCase):
    def test_listed_phrases_match(self):
        for title in (
            'Software Developer Trainee',
            'Junior Software Developer — Java',
            'Data Analyst (Fresher)',
            'Junior Data Analyst',
            'Business Analyst Intern - Chennai',
            'QA Automation Engineer',
            'Digital Marketing Intern',
            'Customer Support Associate',
            'BI Intern',
            'Analytics Engineer',
            'Junior Data Engineer',
            'Graduate Apprentice',
            'Apprentice',
        ):
            self.assertTrue(title_matches_target_role(title), title)

    def test_off_list_titles_rejected(self):
        for title in (
            'Senior Software Engineer',
            'Software Engineer II',
            'Product Manager',
            'Machine Learning Engineer',
            'DevOps Engineer',
            'Staff Engineer',
            '',
            None,
        ):
            self.assertFalse(title_matches_target_role(title), title)

    def test_flexible_whitespace_and_hyphens(self):
        self.assertTrue(title_matches_target_role('Data-Analyst Trainee'))
        self.assertTrue(title_matches_target_role('software  development   intern'))


class CollectionCityGateTests(unittest.TestCase):
    def test_collection_set(self):
        self.assertEqual(COLLECTION_CITY_KEYS, {'chennai', 'bengaluru', 'remote'})

    def test_is_collection_city(self):
        self.assertTrue(is_collection_city('chennai'))
        self.assertTrue(is_collection_city('bengaluru'))
        self.assertTrue(is_collection_city('remote'))
        self.assertFalse(is_collection_city('hyderabad'))
        self.assertFalse(is_collection_city('mumbai'))
        self.assertFalse(is_collection_city(None))

    def test_normalize_then_gate(self):
        self.assertTrue(is_collection_city(normalize_city('Bangalore, Karnataka, India')))
        self.assertTrue(is_collection_city(normalize_city('Chennai')))
        self.assertTrue(is_collection_city(normalize_city('India (Remote)')))
        self.assertFalse(is_collection_city(normalize_city('Hyderabad, Telangana')))

    def test_parse_slash_city_list(self):
        self.assertEqual(
            parse_city_filter_list('chennai/bangalore/remote'),
            ['chennai', 'bengaluru', 'remote'],
        )
        self.assertEqual(parse_city_filter_list('bangalore'), ['bengaluru'])
        self.assertIsNone(parse_city_filter_list(None))
        self.assertIsNone(parse_city_filter_list('all'))
        self.assertEqual(parse_city_filter_list('notacity'), [])


if __name__ == '__main__':
    unittest.main()
