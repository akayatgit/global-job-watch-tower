from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.job_role_families import title_matches_role_family
from app.telegram_job_search import (
    IntentInterpreter,
    JobMasterIntent,
    JobMasterEngine,
    _company_query,
    _fallback_intent,
    canonical_link,
    experience_display,
    parse_window_token,
)
from app.telegram_sessions import TelegramSessionStore


def make_job(
    i: int,
    *,
    title: str = 'Machine Learning Engineer',
    city: str = 'bengaluru',
    company: str | None = None,
    posted_days_ago: int | None = None,
    scraped_hours_ago: int | None = None,
) -> dict:
    job_id = str(4448000000 + i)
    job = {
        'id': i,
        'linkedin_job_id': job_id,
        'title': title,
        'company': company if company is not None else f'Company {i}',
        'city_key': city,
        'experience_band': 'Fresher' if i % 2 else None,
        'source_track': 'fresher',
        'job_url': f'https://www.linkedin.com/jobs/view/broken-title-{job_id}/?tracking=x',
    }
    now = datetime.now(timezone.utc)
    if posted_days_ago is not None:
        job['posted_date'] = (now.date() - timedelta(days=posted_days_ago)).isoformat()
    if scraped_hours_ago is not None:
        job['scraped_at'] = (now - timedelta(hours=scraped_hours_ago)).isoformat()
    return job


class FakeAPI:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.fail_jobs = False
        self.jobs = [make_job(i) for i in range(1, 26)]
        self.jobs += [make_job(80, title='Java Software Engineer')]

    def __call__(self, path: str, params: dict | None = None):
        self.calls.append((path, params or {}))
        if path == '/api/jobs':
            if self.fail_jobs:
                raise OSError('tower unavailable')
            params = params or {}
            rows = list(self.jobs)
            if params.get('company'):
                needle = str(params['company']).lower()
                rows = [
                    row for row in rows
                    if needle in str(row.get('company') or '').lower()
                ]
            if params.get('days') is not None:
                # Mirrors /api/jobs semantics: 0 = scraped_at rolling 24h,
                # else posted_date over the last N days.
                days = int(params['days'])
                now = datetime.now(timezone.utc)
                if days == 0:
                    rows = [
                        row for row in rows
                        if row.get('scraped_at')
                        and datetime.fromisoformat(row['scraped_at']) >= now - timedelta(hours=24)
                    ]
                else:
                    start = now.date() - timedelta(days=days - 1)
                    rows = [
                        row for row in rows
                        if row.get('posted_date')
                        and date.fromisoformat(row['posted_date']) >= start
                    ]
            if params.get('city'):
                rows = [row for row in rows if row.get('city_key') == params['city']]
            if params.get('track'):
                rows = [row for row in rows if row.get('source_track') == params['track']]
            if params.get('role_family'):
                rows = [
                    row for row in rows
                    if title_matches_role_family(row.get('title'), params['role_family'])
                ]
            terms = str(params.get('title_terms') or '').split()
            if terms:
                rows = [
                    row for row in rows
                    if any(term in str(row.get('title') or '').lower() for term in terms)
                ]
            offset = int(params.get('offset') or 0)
            limit = int(params.get('limit') or len(rows))
            return rows[offset:offset + limit]
        if path == '/api/jobs/insights':
            total = 80 if (params or {}).get('city') == 'chennai' else 120
            return {
                'total': total,
                'prior_total': 100,
                'companies': [{'name': 'Acme', 'n': 9}, {'name': 'Beta', 'n': 7}],
                'roles': [{'name': 'AI Engineer', 'n': 11}],
            }
        if path == '/api/ultron/top-companies':
            return {'companies': [{'name': 'Acme', 'n': 9}, {'name': 'Beta', 'n': 7}]}
        if path == '/api/ultron/roles-rank':
            return {'roles': [{'name': 'AI Engineer', 'n': 11}]}
        return {}


class TelegramJobSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = TelegramSessionStore(Path(self.tmp.name) / 'sessions.db')
        self.api = FakeAPI()
        self.engine = JobMasterEngine(
            api_get=self.api,
            interpreter=IntentInterpreter(enabled=False),
            sessions=self.sessions,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_supriya_sentence_understands_scope(self):
        intent = _fallback_intent('Fresh jobs in Bangalore in AI space for fresher')
        self.assertEqual(intent.kind, 'job_search')
        self.assertEqual(intent.cities, ['bengaluru'])
        self.assertEqual(intent.role_family, 'ai_ml')
        self.assertEqual(intent.experience, 'fresher')
        self.assertEqual(intent.role_keywords, [])

    def test_spelling_error_and_long_sentence(self):
        intent = _fallback_intent(
            'hey could you pls maybe show me machin learning jobs for fresh graduate in banglore today'
        )
        self.assertEqual(intent.cities, ['bengaluru'])
        self.assertEqual(intent.experience, 'fresher')
        self.assertEqual(intent.role_family, 'ai_ml')

    def test_specific_technology_is_not_broadened_to_all_software(self):
        intent = _fallback_intent('Java developer jobs in Bangalore')
        self.assertEqual(intent.role_family, 'software')
        self.assertEqual(intent.role_keywords, ['java'])
        self.api.jobs = [
            make_job(1, title='Java Software Engineer'),
            make_job(2, title='Python Software Engineer'),
        ]
        reply = self.engine.handle('Java developer jobs in Bangalore', '42')
        self.assertIn('Java Software Engineer', reply)
        self.assertNotIn('Python Software Engineer', reply)

    def test_common_experience_phrases_map_to_bands(self):
        self.assertEqual(_fallback_intent('Python jobs for 2 years experience').experience, '1-2')
        self.assertEqual(_fallback_intent('Python jobs for 1-3 years').experience, '1-2')
        self.assertEqual(_fallback_intent('Python jobs for 3 to 5 years').experience, '3-5')
        self.assertEqual(_fallback_intent('Python jobs for 6–8 years').experience, '6-8')

    def test_model_cannot_invent_city_or_experience_scope(self):
        intent = IntentInterpreter._validate(
            {
                'kind': 'job_search',
                'cities': ['mumbai'],
                'experience': 'fresher',
                'role_family': 'ai_ml',
            },
            JobMasterIntent(kind='job_search'),
        )
        self.assertEqual(intent.cities, [])
        self.assertEqual(intent.experience, '')

    def test_plural_top_company_and_role_requests_are_insights(self):
        companies = _fallback_intent('Top companies in Bangalore')
        roles = _fallback_intent('Top roles in Chennai')
        self.assertEqual((companies.kind, companies.metric), ('insight', 'top_companies'))
        self.assertEqual((roles.kind, roles.metric), ('insight', 'top_roles'))
        self.assertEqual(companies.role_keywords, [])
        self.assertEqual(roles.role_keywords, [])

    def test_today_and_rolling_24_hours_are_distinct_windows(self):
        self.assertEqual(_fallback_intent('How many jobs today?').window_days, 1)
        self.assertEqual(_fallback_intent('How many jobs in 24h?').window_days, 0)

    def test_first_page_is_ten_verified_rows_and_no_fluff(self):
        reply = self.engine.handle(
            'Fresh jobs in Bangalore in AI space for fresher',
            '1221647274',
        )
        self.assertEqual(reply.count('https://www.linkedin.com/jobs/view/'), 10)
        self.assertIn('1. Machine Learning Engineer — Company 1 — Fresher', reply)
        self.assertIn('2. Machine Learning Engineer — Company 2 — Not stated', reply)
        self.assertIn('Reply more for 10 more jobs.', reply)
        self.assertNotIn('mcp__', reply)
        self.assertNotIn('...', reply)
        self.assertNotIn('How to', reply)
        self.assertNotIn('Watch Tower Data', reply)
        path, params = self.api.calls[0]
        self.assertEqual(path, '/api/jobs')
        self.assertEqual(params['city'], 'bengaluru')
        self.assertEqual(params['track'], 'fresher')
        self.assertEqual(params['role_family'], 'ai_ml')

    def test_more_returns_next_ten_without_duplicates(self):
        first = self.engine.handle('AI jobs Bangalore for freshers', '42')
        second = self.engine.handle('more', '42')
        self.assertIn('1. Machine Learning Engineer', first)
        self.assertIn('11. Machine Learning Engineer', second)
        first_links = {line for line in first.splitlines() if line.startswith('https://')}
        second_links = {line for line in second.splitlines() if line.startswith('https://')}
        self.assertEqual(len(first_links), 10)
        self.assertEqual(len(second_links), 10)
        self.assertFalse(first_links & second_links)

    def test_pagination_survives_process_restart(self):
        self.engine.handle('AI jobs Bangalore for freshers', '42')
        restarted = JobMasterEngine(
            api_get=self.api,
            interpreter=IntentInterpreter(enabled=False),
            sessions=TelegramSessionStore(self.sessions.path),
        )
        reply = restarted.handle('more', '42')
        self.assertIn('11. Machine Learning Engineer', reply)
        self.assertEqual(reply.count('https://www.linkedin.com/jobs/view/'), 10)

    def test_new_arrivals_do_not_duplicate_paginated_jobs(self):
        first = self.engine.handle('AI jobs Bangalore for freshers', '42')
        self.api.jobs.insert(0, make_job(99))
        second = self.engine.handle('more', '42')
        first_links = {line for line in first.splitlines() if line.startswith('https://')}
        second_links = {line for line in second.splitlines() if line.startswith('https://')}
        self.assertFalse(first_links & second_links)

    def test_more_can_scan_beyond_first_thousand_server_matches(self):
        self.api.jobs = [make_job(i) for i in range(1, 1206)]
        intent = _fallback_intent('AI jobs Bangalore for freshers')
        seen = [str(job['linkedin_job_id']) for job in self.api.jobs[:1000]]
        self.sessions.save_search('42', intent.__dict__, page=99, seen_ids=seen)
        reply = self.engine.handle('more', '42')
        self.assertEqual(reply.count('https://www.linkedin.com/jobs/view/'), 10)
        offsets = [params.get('offset') for path, params in self.api.calls if path == '/api/jobs']
        self.assertIn(1000, offsets)

    def test_failed_more_does_not_advance_pagination(self):
        self.engine.handle('AI jobs Bangalore for freshers', '42')
        before = self.sessions.load_search('42')
        self.api.fail_jobs = True
        with self.assertRaises(OSError):
            self.engine.handle('more', '42')
        after = self.sessions.load_search('42')
        self.assertEqual(before, after)

    def test_new_clears_pagination_without_hermes_metadata(self):
        self.engine.handle('AI jobs Bangalore', '42')
        reply = self.engine.handle('/new', '42')
        self.assertEqual(reply, 'Search reset. Send a role, city, or job-market question.')
        self.assertIsNone(self.sessions.load_search('42'))
        for banned in ('qwen', 'Provider', 'Endpoint', 'terminal'):
            self.assertNotIn(banned, reply)

    def test_no_prior_search_more_is_direct(self):
        self.assertEqual(
            self.engine.handle('more', 'unknown'),
            'Send a job search first, then reply more.',
        )

    def test_canonical_link_never_preserves_tracking_or_ellipsis(self):
        job = make_job(3)
        self.assertEqual(
            canonical_link(job),
            f"https://www.linkedin.com/jobs/view/{job['linkedin_job_id']}/",
        )
        self.assertEqual(canonical_link({'job_url': 'https://linkedin.com/jobs/view/...'}), '')
        self.assertEqual(experience_display('1-2'), '1–2 years')
        self.assertEqual(experience_display('13plus'), '13+ years')

    def test_invalid_link_and_non_ai_title_are_excluded(self):
        self.api.jobs = [
            {'title': 'AI Engineer', 'company': 'No Link'},
            make_job(2, title='Java Engineer'),
            make_job(3, title='AI Engineer'),
            {**make_job(4, title='AI Engineer'), 'experience_band': '3-5 years'},
        ]
        reply = self.engine.handle('AI jobs Bangalore for freshers', '42')
        self.assertEqual(reply.count('https://www.linkedin.com/jobs/view/'), 1)
        self.assertIn('AI Engineer — Company 3', reply)
        self.assertNotIn('No Link', reply)
        self.assertNotIn('Java Engineer', reply)

    def test_zero_matches_does_not_widen_search(self):
        self.api.jobs = [make_job(1, title='Finance Manager', city='mumbai')]
        reply = self.engine.handle('AI jobs Bangalore', '42')
        self.assertEqual(reply, 'No verified jobs match that search right now.')
        self.assertEqual(len([c for c in self.api.calls if c[0] == '/api/jobs']), 1)

    def test_grounded_count_insight(self):
        reply = self.engine.handle('How many jobs are there in Bangalore?', '42')
        self.assertEqual(
            reply,
            'Bengaluru — 120 matching jobs in the past 7 days\n'
            'Source — live Watch Tower',
        )
        self.assertEqual(self.api.calls[-1][1]['title_terms'], '')

    def test_role_and_fresher_scope_are_preserved_for_numbers(self):
        self.engine.handle('How many AI fresher jobs are in Bangalore?', '42')
        path, params = self.api.calls[-1]
        self.assertEqual(path, '/api/jobs/insights')
        self.assertEqual(params['city'], 'bengaluru')
        self.assertEqual(params['role_family'], 'ai_ml')
        self.assertEqual(params['track'], 'fresher')

    def test_grounded_city_comparison(self):
        reply = self.engine.handle('Compare Bangalore vs Chennai jobs for 7 days', '42')
        self.assertEqual(
            reply,
            'Bengaluru — 120 jobs\n'
            'Chennai — 80 jobs\n'
            'Difference — 40 jobs\n'
            'Window — past 7 days',
        )


class CompanyJobsTests(unittest.TestCase):
    """Jobs by company with time windows (24h · 7d · this month)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = TelegramSessionStore(Path(self.tmp.name) / 'sessions.db')
        self.api = FakeAPI()
        # Deloitte: 2 caught in 24h (posted today), 1 posted 3 days ago,
        # 2 posted 20 days ago → 24h=2 · 7d=3 · month=5.
        self.api.jobs = [
            make_job(201, title='Audit Analyst', company='Deloitte',
                     posted_days_ago=0, scraped_hours_ago=1),
            make_job(202, title='Risk Advisory Intern', company='Deloitte',
                     posted_days_ago=0, scraped_hours_ago=2),
            make_job(203, title='Tax Consultant', company='Deloitte',
                     posted_days_ago=3, scraped_hours_ago=72),
            make_job(204, title='Data Engineer', company='Deloitte',
                     posted_days_ago=20, scraped_hours_ago=480),
            make_job(205, title='Java Developer', company='Deloitte',
                     posted_days_ago=20, scraped_hours_ago=481),
        ]
        self.engine = JobMasterEngine(
            api_get=self.api,
            interpreter=IntentInterpreter(enabled=False),
            sessions=self.sessions,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_company_query_detection(self):
        self.assertEqual(_company_query('jobs at deloitte'), ('deloitte', 7, True))
        self.assertEqual(_company_query('Jobin Deloitte 24'), ('deloitte', 0, False))
        self.assertEqual(_company_query('deloitte jobs this month'), ('deloitte', 30, False))
        self.assertEqual(_company_query('openings with JPMorganChase this week'), ('jpmorganchase', 7, True))
        self.assertEqual(
            _company_query('jobs at tata consultancy services in chennai'),
            ('tata consultancy services', 7, True),
        )
        # Cities, role families, and filler words are never company names.
        self.assertIsNone(_company_query('jobs in bangalore'))
        self.assertIsNone(_company_query('ai jobs'))
        self.assertIsNone(_company_query('fresher jobs'))
        self.assertIsNone(_company_query('How many jobs today?'))

    def test_window_tokens(self):
        self.assertEqual(parse_window_token('24h'), 0)
        self.assertEqual(parse_window_token('24'), 0)
        self.assertEqual(parse_window_token('today'), 1)
        self.assertEqual(parse_window_token('7'), 7)
        self.assertEqual(parse_window_token('week'), 7)
        self.assertEqual(parse_window_token('30'), 30)
        self.assertEqual(parse_window_token('month'), 30)
        self.assertIsNone(parse_window_token('deloitte'))

    def test_default_window_is_7_days_with_tri_window_header(self):
        reply = self.engine.handle('jobs at deloitte', '42')
        self.assertIn(
            'Deloitte — 3 openings posted in the last 7 days (5 this month · 2 caught in 24h)',
            reply,
        )
        self.assertIn('1. Audit Analyst — Fresher', reply)
        self.assertIn('3. Tax Consultant — Fresher', reply)
        self.assertEqual(reply.count('https://www.linkedin.com/jobs/view/'), 3)
        self.assertNotIn('Data Engineer', reply)

    def test_live_seen_typo_jobin_and_24h_window(self):
        reply = self.engine.handle('Jobin Deloitte 24', '42')
        self.assertIn(
            'Deloitte — 2 openings caught in the last 24 hours (3 in 7 days · 5 this month)',
            reply,
        )
        self.assertEqual(reply.count('https://www.linkedin.com/jobs/view/'), 2)

    def test_this_month_window(self):
        reply = self.engine.handle('deloitte jobs this month', '42')
        self.assertIn(
            'Deloitte — 5 openings posted this month (3 in 7 days · 2 caught in 24h)',
            reply,
        )
        self.assertEqual(reply.count('https://www.linkedin.com/jobs/view/'), 5)

    def test_unknown_company_stated_outright_gets_honest_zero(self):
        reply = self.engine.handle('jobs at hogwarts', '42')
        self.assertEqual(
            reply,
            "I don't see verified Hogwarts openings in the last 7 days. "
            "Try 'top companies hiring' to see who's active right now.",
        )

    def test_ambiguous_non_company_falls_through_to_role_search(self):
        reply = self.engine.handle('python jobs', '42')
        self.assertNotIn('openings posted', reply)
        self.assertEqual(reply, 'No verified jobs match that search right now.')

    def test_short_name_matches_whole_word_only(self):
        self.api.jobs = [
            make_job(301, title='Assurance Associate', company='EY',
                     posted_days_ago=1, scraped_hours_ago=30),
            make_job(302, title='Sensor Engineer', company='Keyence',
                     posted_days_ago=1, scraped_hours_ago=30),
        ]
        reply = self.engine.handle('jobs at ey', '42')
        self.assertIn('EY — 1 opening posted in the last 7 days', reply)
        self.assertIn('Assurance Associate', reply)
        self.assertNotIn('Keyence', reply)
        self.assertNotIn('Sensor Engineer', reply)

    def test_empty_window_with_month_activity_suggests_month(self):
        self.api.jobs = [
            make_job(401, title='Old Role', company='Deloitte',
                     posted_days_ago=20, scraped_hours_ago=480),
        ]
        reply = self.engine.handle('jobs at deloitte 24h', '42')
        self.assertEqual(
            reply,
            "I don't see verified Deloitte openings in the last 24 hours — "
            "this month has 1. Say 'jobs at Deloitte this month' to see them.",
        )

    def test_company_pagination_continues_without_duplicates(self):
        self.api.jobs = [
            make_job(500 + i, title=f'Consultant {i}', company='Deloitte',
                     posted_days_ago=1, scraped_hours_ago=30)
            for i in range(1, 16)
        ]
        first = self.engine.handle('jobs at deloitte', '42')
        second = self.engine.handle('more', '42')
        self.assertIn('openings posted in the last 7 days', first)
        self.assertIn('Reply more for 10 more jobs.', first)
        self.assertNotIn('openings posted', second)
        self.assertIn('11. Consultant', second)
        first_links = {line for line in first.splitlines() if line.startswith('https://')}
        second_links = {line for line in second.splitlines() if line.startswith('https://')}
        self.assertEqual(len(first_links), 10)
        self.assertEqual(len(second_links), 5)
        self.assertFalse(first_links & second_links)

    def test_owner_company_jobs_entry_point_matches_guest_reply(self):
        via_command = self.engine.company_jobs('deloitte', 7, 'owner-chat')
        self.sessions.clear_onboarding('42')
        via_chat = self.engine.handle('jobs at deloitte', '42')
        self.assertEqual(via_command, via_chat)

    def test_company_search_does_not_overwrite_guest_role_profile(self):
        self.engine.handle('jobs at deloitte', '42')
        self.assertIsNone(self.sessions.get_guest_profile('42'))


if __name__ == '__main__':
    unittest.main()
