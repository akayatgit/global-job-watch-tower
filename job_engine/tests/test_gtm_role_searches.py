"""GTM role×city hunting searches + funnel diagnostic (outage fix 2026-08-19).

The tower went empty after the GTM store-gates shipped: company-name
searches never looked where the allowlisted roles are. These tests pin the
fix — dedicated role-group searches per collection city (and Remote via
f_WT=2) whose sentinel target ('*') accepts any watched company at insert.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.gtm_role_searches import (
    GTM_LOCATIONS,
    GTM_ROLE_GROUPS,
    WATCHLIST_ANY,
    gather_watchlist_needles,
    is_watchlist_any,
    seed_gtm_role_searches,
)
from app.mnc_watchlist import (
    company_matches_target,
    seed_watchlist,
    watchlist_roster,
)
from app.models import Company, JobMaster, SearchConfig


def make_session():
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


class SeedGtmRoleSearchesTests(unittest.TestCase):
    def setUp(self):
        self.db = make_session()

    def test_seed_creates_one_search_per_group_and_location(self):
        result = seed_gtm_role_searches(self.db)
        expected = len(GTM_ROLE_GROUPS) * len(GTM_LOCATIONS)
        self.assertEqual(result['created'], expected)
        configs = [
            cfg for cfg in self.db.execute(select(SearchConfig)).scalars()
            if (cfg.target_company or '') == WATCHLIST_ANY
        ]
        self.assertEqual(len(configs), expected)
        for cfg in configs:
            self.assertTrue(cfg.enabled)
            self.assertEqual(cfg.track, 'fresher')
            self.assertEqual(cfg.experience_filter, '1,2')
            self.assertLessEqual(cfg.max_pages, 3)

    def test_seed_is_idempotent(self):
        seed_gtm_role_searches(self.db)
        result = seed_gtm_role_searches(self.db)
        self.assertEqual(result['created'], 0)
        self.assertEqual(
            result['updated'], len(GTM_ROLE_GROUPS) * len(GTM_LOCATIONS),
        )

    def test_remote_searches_carry_the_linkedin_remote_filter(self):
        seed_gtm_role_searches(self.db)
        remote = [
            cfg for cfg in self.db.execute(select(SearchConfig)).scalars()
            if (cfg.location_label or '').startswith('Remote')
        ]
        self.assertEqual(len(remote), len(GTM_ROLE_GROUPS))
        for cfg in remote:
            self.assertEqual(cfg.work_type_filter, '2')

    def test_city_searches_use_city_geo_ids_not_india(self):
        seed_gtm_role_searches(self.db)
        for cfg in self.db.execute(select(SearchConfig)).scalars():
            if (cfg.location_label or '') in ('Chennai', 'Bengaluru'):
                self.assertNotEqual(cfg.geo_id, '102713980', cfg.name)

    def test_gtm_searches_survive_the_mnc_seed_sleep(self):
        """seed_watchlist disables role-keyword searches (empty target) —
        the sentinel '*' must keep GTM hunting searches awake."""
        seed_gtm_role_searches(self.db)
        seed_watchlist(self.db)
        gtm = [
            cfg for cfg in self.db.execute(select(SearchConfig)).scalars()
            if (cfg.target_company or '') == WATCHLIST_ANY
        ]
        self.assertTrue(gtm)
        for cfg in gtm:
            self.assertTrue(cfg.enabled, cfg.name)

    def test_a_disabled_gtm_search_is_reenabled_on_seed(self):
        seed_gtm_role_searches(self.db)
        cfg = next(
            c for c in self.db.execute(select(SearchConfig)).scalars()
            if (c.target_company or '') == WATCHLIST_ANY
        )
        cfg.enabled = False
        self.db.commit()
        seed_gtm_role_searches(self.db)
        self.db.refresh(cfg)
        self.assertTrue(cfg.enabled)

    def test_roster_never_lists_the_sentinel_as_a_company(self):
        seed_watchlist(self.db)
        seed_gtm_role_searches(self.db)
        names = [row['company'] for row in watchlist_roster(self.db)]
        self.assertNotIn('*', names)


class WatchlistAnyGateTests(unittest.TestCase):
    def setUp(self):
        self.db = make_session()
        seed_watchlist(self.db)
        seed_gtm_role_searches(self.db)

    def test_is_watchlist_any(self):
        self.assertTrue(is_watchlist_any('*'))
        self.assertTrue(is_watchlist_any(' * '))
        self.assertFalse(is_watchlist_any('Deloitte'))
        self.assertFalse(is_watchlist_any(''))
        self.assertFalse(is_watchlist_any(None))

    def test_needles_cover_catalogue_and_exclude_sentinel(self):
        needles = gather_watchlist_needles(self.db)
        self.assertIn('Deloitte', needles)
        self.assertIn('TCS', needles)  # alias needle from the pipe entry
        self.assertNotIn('*', needles)

    def test_probe_companies_match_via_needles(self):
        """The live 2026-08-19 probe rows (Barclays, Capgemini, Accenture,
        Wipro at Chennai) must pass the any-watched-company gate."""
        needles = gather_watchlist_needles(self.db)

        def company_ok(name: str) -> bool:
            return any(company_matches_target(name, n) for n in needles)

        for name in ('Barclays', 'Capgemini', 'Accenture in India', 'Wipro', 'Nokia'):
            self.assertTrue(company_ok(name), name)
        for name in ('Guidehouse', 'Babcock Power APAC Pvt. Ltd.', 'RELX'):
            self.assertFalse(company_ok(name), name)


class FunnelEndpointTests(unittest.TestCase):
    def setUp(self):
        self.db = make_session()
        from app.api import routes

        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

    def _add_job(self, *, title: str, city: str | None, verified: bool,
                 min_years: float | None = None, hours_ago: float = 1.0):
        now = datetime.now(timezone.utc)
        company = self.db.execute(
            select(Company).where(Company.name == 'Deloitte')
        ).scalar_one_or_none()
        if company is None:
            company = Company(name='Deloitte')
            self.db.add(company)
            self.db.flush()
        job = JobMaster(
            linkedin_job_id=str(4448100000 + len(self.db.query(JobMaster).all())),
            title=title,
            company_id=company.id,
            location=city or 'India',
            city_key=city,
            sector='tech_digital',
            job_url='https://www.linkedin.com/jobs/view/1/',
            raw_text='',
            source_track='fresher',
            scraped_at=now - timedelta(hours=hours_ago),
            requirements_enriched_at=(now if verified else None),
            experience_min_years=min_years,
            experience_max_years=min_years,
        )
        self.db.add(job)
        self.db.commit()

    def test_funnel_counts_each_gate(self):
        # Servable gem: allowlisted role, collection city, verified, fresher title
        self._add_job(title='Data Analyst (Fresher)', city='chennai', verified=True)
        # Caught but wrong city (pre-gate legacy row)
        self._add_job(title='Data Analyst', city='hyderabad', verified=True, min_years=3.0)
        # In-city but pending verification
        self._add_job(title='Junior Data Analyst', city='bengaluru', verified=False)
        # Outside the window entirely
        self._add_job(title='Data Analyst', city='chennai', verified=True, hours_ago=30)

        data = self.client.get('/api/jobs/funnel?hours=24').json()
        self.assertEqual(data['caught'], 3)
        self.assertEqual(data['in_collection_cities'], 2)
        self.assertEqual(data['role_matched'], 3)
        self.assertEqual(data['detail_verified'], 2)
        self.assertEqual(data['servable_fresher'], 1)
        self.assertEqual(data['pending_verification'], 1)
        self.assertEqual(data['total_all_time'], 4)
        self.assertIsNotNone(data['last_catch_at'])

    def test_empty_tower_reports_zeros_not_errors(self):
        data = self.client.get('/api/jobs/funnel').json()
        self.assertEqual(data['caught'], 0)
        self.assertEqual(data['servable_fresher'], 0)
        self.assertIsNone(data['last_catch_at'])


if __name__ == '__main__':
    unittest.main()
