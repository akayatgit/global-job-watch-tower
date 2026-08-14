"""MNC-first collection base (Ashok's pivot, 2026-08-14).

The niche: graduates chasing the MNC dream. Collection flips from role
keywords to a curated company watchlist — complete data on the giants only.
Covers: catalogue sanity, the company precision gate, seeding (role
searches sleep, never deleted), and /addcompany idempotency.
"""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.mnc_watchlist import (
    MNC_CATALOGUE,
    add_watch_company,
    company_matches_target,
    display_name,
    needles,
    seed_watchlist,
)
from app.models import Company, SearchConfig


def make_session():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


class CatalogueTests(unittest.TestCase):
    def test_catalogue_entries_are_wellformed_and_unique(self):
        seen: set[str] = set()
        for entry in MNC_CATALOGUE:
            parts = needles(entry)
            self.assertTrue(parts, entry)
            for needle in parts:
                key = needle.lower()
                self.assertNotIn(key, seen, f'duplicate needle: {needle}')
                seen.add(key)

    def test_the_named_giants_are_present(self):
        displays = {display_name(entry).lower() for entry in MNC_CATALOGUE}
        for name in ('deloitte', 'oracle', 'apple', 'google'):
            self.assertIn(name, displays)


class CompanyMatchTests(unittest.TestCase):
    def test_subsidiaries_and_entities_match(self):
        self.assertTrue(company_matches_target('Deloitte USI', 'Deloitte'))
        self.assertTrue(company_matches_target('Deloitte Consulting', 'Deloitte'))
        self.assertTrue(company_matches_target('Amazon Web Services (AWS)', 'Amazon'))
        self.assertTrue(company_matches_target('Google India', 'Google'))
        self.assertTrue(company_matches_target('Siemens Healthineers', 'Siemens'))

    def test_short_needles_never_match_inside_other_words(self):
        # 'Visa' the giant must never keep 'Visakha Industries' rows.
        self.assertFalse(company_matches_target('Visakha Industries', 'Visa'))
        self.assertTrue(company_matches_target('Visa', 'Visa'))
        self.assertFalse(company_matches_target('Keyence', 'EY'))
        self.assertTrue(company_matches_target('EY Global Delivery Services', 'EY'))

    def test_pipe_needles_absorb_linkedin_naming_drift(self):
        target = 'JPMorganChase|JPMorgan'
        self.assertTrue(company_matches_target('JPMorganChase', target))
        self.assertTrue(company_matches_target('JPMorgan Chase & Co.', target))
        self.assertFalse(company_matches_target('Chase Elevators', target))
        tcs = 'Tata Consultancy Services|TCS'
        self.assertTrue(company_matches_target('Tata Consultancy Services', tcs))
        self.assertTrue(company_matches_target('TCS iON', tcs))
        self.assertFalse(company_matches_target('Tata Motors', tcs))

    def test_empty_inputs_are_safe(self):
        self.assertFalse(company_matches_target(None, 'Deloitte'))
        self.assertFalse(company_matches_target('', 'Deloitte'))
        self.assertFalse(company_matches_target('Deloitte', ''))


class SeedWatchlistTests(unittest.TestCase):
    def setUp(self):
        self.db = make_session()

    def test_seed_creates_one_fresher_search_per_giant(self):
        result = seed_watchlist(self.db)
        self.assertEqual(result['created'], len(MNC_CATALOGUE))
        configs = self.db.execute(select(SearchConfig)).scalars().all()
        self.assertEqual(len(configs), len(MNC_CATALOGUE))
        for cfg in configs:
            self.assertTrue(cfg.enabled)
            self.assertEqual(cfg.track, 'fresher')
            self.assertEqual(cfg.experience_filter, '1,2')
            self.assertTrue((cfg.target_company or '').strip(), cfg.name)
            self.assertTrue(cfg.keywords.startswith('"'), cfg.keywords)
        watched = self.db.execute(
            select(Company).where(Company.watched.is_(True))
        ).scalars().all()
        self.assertEqual(len(watched), len(MNC_CATALOGUE))

    def test_seed_is_idempotent(self):
        seed_watchlist(self.db)
        result = seed_watchlist(self.db)
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['existing'], len(MNC_CATALOGUE))
        configs = self.db.execute(select(SearchConfig)).scalars().all()
        self.assertEqual(len(configs), len(MNC_CATALOGUE))

    def test_seed_sleeps_role_searches_but_never_deletes_them(self):
        role_cfg = SearchConfig(
            name='Junior Data Analyst', keywords='junior data analyst',
            enabled=True, schedule_cron='0 5 * * *',
        )
        self.db.add(role_cfg)
        self.db.commit()
        result = seed_watchlist(self.db)
        self.assertEqual(result['role_searches_slept'], 1)
        self.db.refresh(role_cfg)
        self.assertFalse(role_cfg.enabled)
        self.assertIsNotNone(
            self.db.execute(
                select(SearchConfig).where(SearchConfig.name == 'Junior Data Analyst')
            ).scalar_one_or_none()
        )

    def test_seed_never_touches_phone_added_companies(self):
        cfg, created = add_watch_company(self.db, 'Nvidia Graphics Pvt')
        self.db.commit()
        self.assertTrue(created)
        seed_watchlist(self.db)
        self.db.refresh(cfg)
        self.assertTrue(cfg.enabled)


class AddWatchCompanyTests(unittest.TestCase):
    def setUp(self):
        self.db = make_session()
        seed_watchlist(self.db)

    def test_add_new_company_creates_config_and_watched_company(self):
        cfg, created = add_watch_company(self.db, 'Stripe')
        self.db.commit()
        self.assertTrue(created)
        self.assertEqual(cfg.target_company, 'Stripe')
        self.assertEqual(cfg.name, 'MNC · Stripe — Fresher')
        self.assertEqual(cfg.keywords, '"Stripe"')
        self.assertEqual(cfg.experience_filter, '1,2')
        company = self.db.execute(
            select(Company).where(Company.name == 'Stripe')
        ).scalar_one()
        self.assertTrue(company.watched)

    def test_adding_an_existing_giant_is_idempotent(self):
        cfg, created = add_watch_company(self.db, 'Deloitte')
        self.assertFalse(created)
        self.assertEqual(display_name(cfg.target_company), 'Deloitte')

    def test_alias_needle_never_duplicates_the_catalogue_entry(self):
        # 'TCS' is an alias needle of 'Tata Consultancy Services|TCS'.
        cfg, created = add_watch_company(self.db, 'TCS')
        self.assertFalse(created)
        self.assertEqual(display_name(cfg.target_company), 'Tata Consultancy Services')

    def test_adding_reenables_a_disabled_company_watch(self):
        cfg, _ = add_watch_company(self.db, 'Stripe')
        self.db.commit()
        cfg.enabled = False
        self.db.commit()
        again, created = add_watch_company(self.db, 'Stripe')
        self.assertFalse(created)
        self.assertTrue(again.enabled)

    def test_blank_name_is_rejected(self):
        cfg, created = add_watch_company(self.db, '   ')
        self.assertIsNone(cfg)
        self.assertFalse(created)


if __name__ == '__main__':
    unittest.main()
