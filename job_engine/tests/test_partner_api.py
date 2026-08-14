"""AvatarPitch partner API tests (contract 2026-08-14).

Covers: the bearer-token gate (disabled → 503, wrong/missing → 401,
correct → 200), the jobs query thinking (freshness with posted-date
fallback, skill matching over title+description, experience band filter,
city filter, require_logo, one-per-company dedupe, freshest-first order,
months conversion, verbatim serialization), reel suggestions, and health.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import partner
from app.db import Base, get_db
from app.models import Company, JobMaster


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def make_session():
    # StaticPool + check_same_thread=False: one shared in-memory database,
    # reachable from TestClient's worker thread too.
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def add_company(db, name: str, *, logo: bool = True) -> Company:
    company = Company(name=name, logo_url=f'https://cdn.example/{name}.png' if logo else None)
    db.add(company)
    db.flush()
    return company


_seq = iter(range(1, 10_000))


def add_job(
    db,
    *,
    title: str = 'Data Analyst',
    company: Company | None = None,
    posted_days_ago: int | None = 1,
    scraped_days_ago: float = 0,
    band: str | None = 'Fresher',
    min_years: float | None = 0,
    max_years: float | None = 2,
    label: str | None = '0-2 years',
    city: str | None = 'bengaluru',
    description: str | None = None,
    degrees: list | None = None,
) -> JobMaster:
    n = next(_seq)
    job = JobMaster(
        linkedin_job_id=str(4448000000 + n),
        title=title,
        company_id=company.id if company else None,
        location='Bengaluru, Karnataka, India',
        city_key=city,
        job_url=f'https://www.linkedin.com/jobs/view/{4448000000 + n}/',
        posted_date=(date.today() - timedelta(days=posted_days_ago)) if posted_days_ago is not None else None,
        scraped_at=utcnow() - timedelta(days=scraped_days_ago),
        experience_band=band,
        experience_min_years=min_years,
        experience_max_years=max_years,
        experience_label=label,
        description_text=description,
        degrees=degrees,
        source_track='fresher',
    )
    db.add(job)
    db.flush()
    return job


# ---------------------------------------------------------------------------
# Query thinking (pure functions on a session)
# ---------------------------------------------------------------------------

class PartnerJobsQueryTests(unittest.TestCase):
    def setUp(self):
        self.db = make_session()

    def tearDown(self):
        self.db.close()

    def test_verbatim_serialization_and_months_conversion(self):
        company = add_company(self.db, 'Acme Analytics')
        add_job(
            self.db, company=company, title='Data Analyst',
            min_years=0, max_years=2, label='0-2 years',
            degrees=['B.E/B.Tech', 'MCA'],
        )
        jobs, total = partner.query_partner_jobs(self.db)
        self.assertEqual(total, 1)
        job = jobs[0]
        self.assertEqual(job.company_name, 'Acme Analytics')
        self.assertEqual(job.role_title, 'Data Analyst')
        self.assertEqual(job.experience_min_months, 0)
        self.assertEqual(job.experience_max_months, 24)
        self.assertEqual(job.education, ['B.E/B.Tech', 'MCA'])
        self.assertEqual(job.source, 'linkedin')
        self.assertTrue(job.apply_url.startswith('https://www.linkedin.com/jobs/view/'))

    def test_fresh_days_excludes_stale_posted_dates(self):
        company = add_company(self.db, 'FreshCo')
        add_job(self.db, company=company, posted_days_ago=1)
        add_job(self.db, company=add_company(self.db, 'StaleCo'), posted_days_ago=20)
        jobs, total = partner.query_partner_jobs(self.db, fresh_days=7)
        self.assertEqual(total, 1)
        self.assertEqual(jobs[0].company_name, 'FreshCo')

    def test_null_posted_date_falls_back_to_recent_scrape(self):
        company = add_company(self.db, 'SilentDateCo')
        add_job(self.db, company=company, posted_days_ago=None, scraped_days_ago=0.5)
        add_job(
            self.db, company=add_company(self.db, 'OldSilentCo'),
            posted_days_ago=None, scraped_days_ago=20,
        )
        jobs, total = partner.query_partner_jobs(self.db, fresh_days=7)
        self.assertEqual(total, 1)
        self.assertEqual(jobs[0].company_name, 'SilentDateCo')

    def test_skill_matches_title_or_description(self):
        add_job(self.db, company=add_company(self.db, 'TitleCo'), title='SQL Developer')
        add_job(
            self.db, company=add_company(self.db, 'DescCo'),
            title='Data Analyst', description='Must know SQL and Excel.',
        )
        add_job(self.db, company=add_company(self.db, 'NoMatchCo'), title='HR Executive')
        jobs, total = partner.query_partner_jobs(self.db, skill='sql')
        self.assertEqual(total, 2)
        self.assertEqual({j.company_name for j in jobs}, {'TitleCo', 'DescCo'})

    def test_experience_band_filter(self):
        add_job(self.db, company=add_company(self.db, 'FresherCo'), band='Fresher')
        add_job(self.db, company=add_company(self.db, 'SeniorCo'), band='9-12 years')
        jobs, _total = partner.query_partner_jobs(self.db, experience='fresher')
        self.assertEqual([j.company_name for j in jobs], ['FresherCo'])

    def test_city_filter(self):
        add_job(self.db, company=add_company(self.db, 'BlrCo'), city='bengaluru')
        add_job(self.db, company=add_company(self.db, 'ChennaiCo'), city='chennai')
        jobs, _total = partner.query_partner_jobs(self.db, city='Chennai')
        self.assertEqual([j.company_name for j in jobs], ['ChennaiCo'])

    def test_require_logo_excludes_logoless_and_orphan_jobs(self):
        add_job(self.db, company=add_company(self.db, 'LogoCo', logo=True))
        add_job(self.db, company=add_company(self.db, 'NoLogoCo', logo=False))
        add_job(self.db, company=None)
        jobs, total = partner.query_partner_jobs(self.db, require_logo=True)
        self.assertEqual(total, 1)
        self.assertEqual(jobs[0].company_name, 'LogoCo')
        jobs_all, total_all = partner.query_partner_jobs(self.db, require_logo=False)
        self.assertEqual(total_all, 3)
        self.assertEqual(len(jobs_all), 3)

    def test_one_per_company_keeps_the_freshest_card(self):
        company = add_company(self.db, 'BigHirer')
        add_job(self.db, company=company, title='Older Role', posted_days_ago=3)
        add_job(self.db, company=company, title='Newest Role', posted_days_ago=1)
        jobs, total = partner.query_partner_jobs(self.db, one_per_company=True)
        self.assertEqual(total, 2)  # total counts matches before dedupe
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].role_title, 'Newest Role')

    def test_freshest_first_ordering_and_limit(self):
        for days_ago, name in ((3, 'ThreeDays'), (1, 'OneDay'), (2, 'TwoDays')):
            add_job(self.db, company=add_company(self.db, name), posted_days_ago=days_ago)
        jobs, _total = partner.query_partner_jobs(self.db, limit=2)
        self.assertEqual([j.company_name for j in jobs], ['OneDay', 'TwoDays'])


class ReelSuggestionsTests(unittest.TestCase):
    def setUp(self):
        self.db = make_session()

    def tearDown(self):
        self.db.close()

    def test_suggestions_ranked_with_logo_company_counts(self):
        logo_co = add_company(self.db, 'LogoCo', logo=True)
        plain_co = add_company(self.db, 'PlainCo', logo=False)
        for _ in range(4):
            add_job(self.db, company=logo_co, title='SQL Developer')
        add_job(self.db, company=plain_co, title='Junior SQL Analyst')
        add_job(self.db, company=logo_co, title='Python Intern')  # below min_jobs

        suggestions = partner.query_reel_suggestions(self.db, min_jobs=4)
        self.assertEqual(len(suggestions), 1)
        top = suggestions[0]
        self.assertEqual(top.skill, 'sql')
        self.assertEqual(top.active_jobs, 5)
        self.assertEqual(top.companies_with_logo, 1)

    def test_stale_jobs_do_not_count(self):
        company = add_company(self.db, 'OldCo')
        for _ in range(5):
            add_job(self.db, company=company, title='SQL Developer', posted_days_ago=25)
        self.assertEqual(partner.query_reel_suggestions(self.db, fresh_days=7, min_jobs=1), [])


# ---------------------------------------------------------------------------
# HTTP surface — auth gate + wiring (TestClient on an isolated app)
# ---------------------------------------------------------------------------

class PartnerHttpTests(unittest.TestCase):
    def setUp(self):
        self.db = make_session()
        app = FastAPI()
        app.include_router(partner.router)

        def override_get_db():
            yield self.db

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()

    def test_token_unset_means_disabled_503(self):
        with mock.patch.object(partner.config, 'PARTNER_API_TOKEN', ''):
            response = self.client.get(
                '/api/partner/v1/health',
                headers={'Authorization': 'Bearer anything'},
            )
        self.assertEqual(response.status_code, 503)

    def test_missing_or_wrong_token_is_401(self):
        with mock.patch.object(partner.config, 'PARTNER_API_TOKEN', 'secret-token'):
            self.assertEqual(self.client.get('/api/partner/v1/jobs').status_code, 401)
            response = self.client.get(
                '/api/partner/v1/jobs',
                headers={'Authorization': 'Bearer wrong'},
            )
        self.assertEqual(response.status_code, 401)

    def test_jobs_endpoint_end_to_end(self):
        company = add_company(self.db, 'Acme Analytics')
        add_job(self.db, company=company, title='SQL Developer', degrees=['B.E/B.Tech'])
        self.db.commit()
        with mock.patch.object(partner.config, 'PARTNER_API_TOKEN', 'secret-token'):
            response = self.client.get(
                '/api/partner/v1/jobs',
                params={'skill': 'sql', 'experience': 'fresher'},
                headers={'Authorization': 'Bearer secret-token'},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['total_matched'], 1)
        row = payload['jobs'][0]
        self.assertEqual(row['company_name'], 'Acme Analytics')
        self.assertEqual(row['role_title'], 'SQL Developer')
        self.assertEqual(row['education'], ['B.E/B.Tech'])
        self.assertIn('generated_at', payload)

    def test_unknown_experience_band_is_422(self):
        with mock.patch.object(partner.config, 'PARTNER_API_TOKEN', 'secret-token'):
            response = self.client.get(
                '/api/partner/v1/jobs',
                params={'experience': 'ninja'},
                headers={'Authorization': 'Bearer secret-token'},
            )
        self.assertEqual(response.status_code, 422)

    def test_health_reports_totals(self):
        add_job(self.db, company=add_company(self.db, 'AnyCo'))
        self.db.commit()
        with mock.patch.object(partner.config, 'PARTNER_API_TOKEN', 'secret-token'):
            response = self.client.get(
                '/api/partner/v1/health',
                headers={'Authorization': 'Bearer secret-token'},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['jobs_total'], 1)
        self.assertIsNotNone(payload['freshest_scrape_at'])


if __name__ == '__main__':
    unittest.main()
