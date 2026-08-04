from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.telegram_job_search import (
    IntentInterpreter,
    JobMasterIntent,
    JobMasterEngine,
    _fallback_intent,
    canonical_link,
    experience_display,
)
from app.telegram_sessions import TelegramSessionStore


def make_job(i: int, *, title: str = 'Machine Learning Engineer', city: str = 'bengaluru') -> dict:
    job_id = str(4448000000 + i)
    return {
        'id': i,
        'linkedin_job_id': job_id,
        'title': title,
        'company': f'Company {i}',
        'city_key': city,
        'experience_band': 'Fresher' if i % 2 else None,
        'source_track': 'fresher',
        'job_url': f'https://www.linkedin.com/jobs/view/broken-title-{job_id}/?tracking=x',
    }


class FakeAPI:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.jobs = [make_job(i) for i in range(1, 26)]
        self.jobs += [make_job(80, title='Java Software Engineer')]

    def __call__(self, path: str, params: dict | None = None):
        self.calls.append((path, params or {}))
        if path == '/api/jobs':
            return self.jobs
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
        ]
        reply = self.engine.handle('AI jobs Bangalore', '42')
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


if __name__ == '__main__':
    unittest.main()
