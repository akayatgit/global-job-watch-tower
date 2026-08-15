"""AI description reading — grounded, never authored (Ashok, 2026-08-15:
"Use AI to understand detailed descriptions of jobs").

The model reads stored description_text and reports employer experience
statements; a deterministic validator requires every claim to carry a
VERBATIM quote found in the description. These tests lock the grounding:
hallucinated quotes, negated fresher statements, and numberless years
quotes must all be discarded, and regex-parsed years must never be
overwritten by the model.
"""

from __future__ import annotations

import json
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.ai_requirements import (
    AIReading,
    apply_reading,
    pending_ai_read_ids,
    validate_reading,
)
from app.db import Base
from app.models import JobMaster
from app.models.models import utcnow
from app.seniority import is_mandatory_fresher

DESC = (
    'About the role. We are hiring for our data team in Bengaluru. '
    'Freshers and fresh graduates are welcome to apply for this role. '
    'Candidates having up to one year of exposure may also apply. '
    'Good knowledge of SQL is expected. This position requires 0-1 years '
    'of experience in analytics. Qualification: B.Tech or MCA in any stream. '
    'Skills required: SQL, Python and Excel. '
    'Industry: IT Services and IT Consulting. '
    'Salary: INR 4,50,000 - 6,00,000 per annum.'
)

SENIOR_DESC = (
    'We are looking for an experienced engineer. '
    'A minimum of 5 years of experience with Zscaler is required. '
    'This role is not suitable for freshers.'
)


def reply(experience=None, fresher=None, **extras) -> str:
    payload = {
        'experience': experience or {'min_years': None, 'max_years': None, 'quote': None},
        'fresher_statement': fresher or {'present': False, 'quote': None},
    }
    payload.update(extras)
    return json.dumps(payload)


class ValidateReadingTests(unittest.TestCase):
    def test_grounded_years_claim_is_accepted(self):
        reading = validate_reading(reply(experience={
            'min_years': 0, 'max_years': 1,
            'quote': 'This position requires 0-1 years of experience in analytics.',
        }), DESC)
        self.assertEqual(reading.min_years, 0.0)
        self.assertEqual(reading.max_years, 1.0)
        self.assertIn('0-1 years', reading.years_quote)

    def test_grounded_fresher_statement_is_accepted(self):
        reading = validate_reading(reply(fresher={
            'present': True,
            'quote': 'Freshers and fresh graduates are welcome to apply for this role.',
        }), DESC)
        self.assertTrue(reading.explicit_fresher)
        self.assertIn('Freshers', reading.fresher_quote)

    def test_hallucinated_quote_is_discarded(self):
        # The model invents a sentence that is NOT in the description —
        # the claim it carries must die at validation.
        reading = validate_reading(reply(fresher={
            'present': True,
            'quote': 'We proudly welcome freshers with open arms and great pay.',
        }), DESC)
        self.assertFalse(reading.explicit_fresher)
        self.assertIsNone(reading.fresher_quote)

    def test_negated_fresher_statement_is_rejected(self):
        reading = validate_reading(reply(fresher={
            'present': True,
            'quote': 'This role is not suitable for freshers.',
        }), SENIOR_DESC)
        self.assertFalse(reading.explicit_fresher)

    def test_years_quote_without_a_number_is_rejected(self):
        reading = validate_reading(reply(experience={
            'min_years': 0, 'max_years': 1,
            'quote': 'Good knowledge of SQL is expected.',
        }), DESC)
        self.assertIsNone(reading.min_years)

    def test_fresher_quote_without_fresher_wording_is_rejected(self):
        # Grounded sentence, but it says nothing about freshers/experience —
        # a lazy model must not launder an arbitrary quote into a verdict.
        reading = validate_reading(reply(fresher={
            'present': True,
            'quote': 'Good knowledge of SQL is expected.',
        }), DESC)
        self.assertFalse(reading.explicit_fresher)

    def test_quote_grounding_ignores_case_and_whitespace(self):
        reading = validate_reading(reply(fresher={
            'present': True,
            'quote': 'freshers  and Fresh   graduates are welcome to apply for this role.',
        }), DESC)
        self.assertTrue(reading.explicit_fresher)

    def test_insane_years_are_rejected_and_swapped_ranges_fixed(self):
        bad = validate_reading(reply(experience={
            'min_years': 99, 'max_years': None,
            'quote': 'This position requires 0-1 years of experience in analytics.',
        }), DESC)
        self.assertIsNone(bad.min_years)
        swapped = validate_reading(reply(experience={
            'min_years': 1, 'max_years': 0,
            'quote': 'This position requires 0-1 years of experience in analytics.',
        }), DESC)
        self.assertEqual((swapped.min_years, swapped.max_years), (0.0, 1.0))

    def test_unusable_reply_returns_none(self):
        self.assertIsNone(validate_reading('I think this job is for freshers!', DESC))
        self.assertIsNone(validate_reading('', DESC))


class EmployerFactsValidationTests(unittest.TestCase):
    """Qualifications / skills / industry / salary — all only if mentioned,
    every item grounded verbatim in the description (Ashok, 2026-08-15)."""

    def test_grounded_facts_are_all_accepted(self):
        reading = validate_reading(reply(
            qualifications=['B.Tech', 'MCA'],
            skills=['SQL', 'Python', 'Excel'],
            industry='IT Services and IT Consulting',
            salary='INR 4,50,000 - 6,00,000 per annum',
        ), DESC)
        self.assertEqual(reading.qualifications, ['B.Tech', 'MCA'])
        self.assertEqual(reading.skills, ['SQL', 'Python', 'Excel'])
        self.assertEqual(reading.industry, 'IT Services and IT Consulting')
        self.assertEqual(reading.salary_text, 'INR 4,50,000 - 6,00,000 per annum')

    def test_hallucinated_items_are_dropped_one_by_one(self):
        reading = validate_reading(reply(
            qualifications=['B.Tech', 'PhD in Astrophysics'],
            skills=['SQL', 'Kubernetes'],
        ), DESC)
        self.assertEqual(reading.qualifications, ['B.Tech'])
        self.assertEqual(reading.skills, ['SQL'])

    def test_unmentioned_facts_stay_none(self):
        reading = validate_reading(reply(), DESC)
        self.assertIsNone(reading.qualifications)
        self.assertIsNone(reading.skills)
        self.assertIsNone(reading.industry)
        self.assertIsNone(reading.salary_text)

    def test_hallucinated_industry_and_salary_are_rejected(self):
        reading = validate_reading(reply(
            industry='Quantum Blockchain Consulting',
            salary='USD 250,000 per year plus equity',
        ), DESC)
        self.assertIsNone(reading.industry)
        self.assertIsNone(reading.salary_text)

    def test_salary_needs_money_evidence_not_any_grounded_sentence(self):
        # Grounded sentence, but it is not a salary — a lazy model must not
        # launder arbitrary text into the salary field.
        reading = validate_reading(reply(
            salary='Good knowledge of SQL is expected.',
        ), DESC)
        self.assertIsNone(reading.salary_text)

    def test_duplicate_and_junk_items_are_filtered(self):
        reading = validate_reading(reply(
            skills=['SQL', 'sql', '', 'x' * 200, 42],
        ), DESC)
        self.assertEqual(reading.skills, ['SQL'])


class ApplyReadingTests(unittest.TestCase):
    def _job(self, **kwargs) -> JobMaster:
        base = dict(
            linkedin_job_id='1', title='Data Analyst',
            job_url='https://www.linkedin.com/jobs/view/1/',
        )
        base.update(kwargs)
        return JobMaster(**base)

    def test_regex_years_are_never_overwritten(self):
        job = self._job(experience_min_years=3.0, experience_max_years=6.0,
                        experience_label='3-6 years')
        apply_reading(job, AIReading(
            explicit_fresher=True, min_years=0.0, max_years=1.0,
            fresher_quote='Freshers welcome', years_quote='0-1 years',
        ))
        self.assertEqual(job.experience_min_years, 3.0)
        self.assertEqual(job.experience_label, '3-6 years')
        # Verdict stored — but stated 3-6 years still veto the law.
        self.assertTrue(job.ai_fresher_verdict)
        self.assertFalse(is_mandatory_fresher(
            job.title, job.experience_min_years, job.experience_max_years,
            job.ai_fresher_verdict,
        ))

    def test_ai_years_fill_the_gap_with_provenance_label(self):
        job = self._job()
        apply_reading(job, AIReading(
            explicit_fresher=False, min_years=0.0, max_years=1.0,
            fresher_quote=None, years_quote='requires 0-1 years of experience',
        ))
        self.assertEqual(job.experience_min_years, 0.0)
        self.assertEqual(job.experience_max_years, 1.0)
        self.assertEqual(job.experience_label, '0-1 years (AI-read)')
        self.assertEqual(job.experience_band, 'Fresher')
        self.assertTrue(is_mandatory_fresher(
            job.title, job.experience_min_years, job.experience_max_years,
            job.ai_fresher_verdict,
        ))

    def test_negative_verdict_is_stored_as_false_not_null(self):
        job = self._job()
        apply_reading(job, AIReading(
            explicit_fresher=False, min_years=None, max_years=None,
            fresher_quote=None, years_quote=None,
        ))
        self.assertIs(job.ai_fresher_verdict, False)
        self.assertIsNotNone(job.ai_read_at)

    def test_qualifications_merge_into_degrees_without_duplicates(self):
        job = self._job(degrees=['B.Tech'])
        notes = apply_reading(job, AIReading(
            explicit_fresher=False, min_years=None, max_years=None,
            fresher_quote=None, years_quote=None,
            qualifications=['b.tech', 'MCA'],
        ))
        # Regex-found degree keeps first place; only genuinely new ones join.
        self.assertEqual(job.degrees, ['B.Tech', 'MCA'])
        self.assertTrue(any('qualifications' in n for n in notes))

    def test_skills_salary_stored_and_linkedin_industry_never_overwritten(self):
        job = self._job(industry='IT Services and IT Consulting')
        apply_reading(job, AIReading(
            explicit_fresher=False, min_years=None, max_years=None,
            fresher_quote=None, years_quote=None,
            skills=['SQL', 'Python'],
            industry='Software Development',
            salary_text='INR 4,50,000 - 6,00,000 per annum',
        ))
        self.assertEqual(job.skills, ['SQL', 'Python'])
        self.assertEqual(job.salary_text, 'INR 4,50,000 - 6,00,000 per annum')
        # LinkedIn's own criteria block outranks the AI fallback.
        self.assertEqual(job.industry, 'IT Services and IT Consulting')

    def test_ai_industry_fills_the_gap_when_criteria_had_none(self):
        job = self._job()
        apply_reading(job, AIReading(
            explicit_fresher=False, min_years=None, max_years=None,
            fresher_quote=None, years_quote=None,
            industry='IT Services and IT Consulting',
        ))
        self.assertEqual(job.industry, 'IT Services and IT Consulting')


class _FakeSel(list):
    def getall(self):
        return list(self)


class _FakeCriteriaItem:
    def __init__(self, label: str, value: str):
        self._label = label
        self._value = value

    def css(self, selector: str):
        if 'h3' in selector or 't-bold' in selector:
            return _FakeSel([self._label])
        return _FakeSel([self._value])


class _FakeJobPage:
    DESC = (
        'We are hiring a data analyst for our Bengaluru team. Freshers are '
        'welcome. Strong SQL knowledge preferred. Apply now to join us.'
    )

    def css(self, selector: str):
        if selector == '.jobs-description__content ::text':
            return _FakeSel([self.DESC])
        if selector.startswith('li.description__job-criteria-item'):
            return [
                _FakeCriteriaItem('Seniority level', 'Entry level'),
                _FakeCriteriaItem('Employment type', 'Full-time'),
                _FakeCriteriaItem('Industries', 'IT Services and IT Consulting'),
            ]
        return _FakeSel([])


class ParseJobDetailIndustriesTests(unittest.TestCase):
    def test_criteria_block_industries_are_captured(self):
        from app.scraper.detail import parse_job_detail

        detail = parse_job_detail(_FakeJobPage())
        self.assertEqual(detail.industries, 'IT Services and IT Consulting')
        self.assertEqual(detail.seniority, 'Entry level')
        self.assertEqual(detail.employment_type, 'Full-time')


class LinkedInIndustriesCriteriaTests(unittest.TestCase):
    """LinkedIn's own criteria block names the industry — deterministic, it
    lands on the job at enrich time and outranks the AI-read fallback."""

    def _detail(self, industries):
        from app.scraper.detail import DetailParse
        from app.scraper.requirements import JobRequirements

        return DetailParse(
            description='x' * 200,
            seniority=None,
            employment_type=None,
            requirements=JobRequirements(description_text='x' * 200),
            industries=industries,
        )

    def test_criteria_industry_lands_on_the_job(self):
        from app.enrichment import _apply_requirements

        job = JobMaster(
            linkedin_job_id='9', title='Data Analyst',
            job_url='https://www.linkedin.com/jobs/view/9/',
        )
        _apply_requirements(job, self._detail('IT Services and IT Consulting'))
        self.assertEqual(job.industry, 'IT Services and IT Consulting')

    def test_missing_criteria_leaves_industry_untouched(self):
        from app.enrichment import _apply_requirements

        job = JobMaster(
            linkedin_job_id='9', title='Data Analyst',
            job_url='https://www.linkedin.com/jobs/view/9/',
            industry='Software Development',
        )
        _apply_requirements(job, self._detail(None))
        self.assertEqual(job.industry, 'Software Development')


class MandatoryLawWithAITests(unittest.TestCase):
    def test_ai_statement_qualifies_only_without_stated_years(self):
        self.assertTrue(is_mandatory_fresher('Data Analyst', None, None, True))
        self.assertFalse(is_mandatory_fresher('Data Analyst', 3.0, 6.0, True))
        self.assertFalse(is_mandatory_fresher('Data Analyst', None, None, False))
        self.assertFalse(is_mandatory_fresher('Data Analyst', None, None, None))

    def test_seniority_title_vetoes_the_ai_verdict_too(self):
        self.assertFalse(is_mandatory_fresher('Senior Data Analyst', None, None, True))

    def test_clause_contains_the_ai_path(self):
        from app.seniority import mandatory_fresher_clause

        sql = str(mandatory_fresher_clause().compile(compile_kwargs={'literal_binds': True}))
        self.assertIn('ai_fresher_verdict', sql)


class PendingAIReadTests(unittest.TestCase):
    def test_only_enriched_unread_rows_with_descriptions_qualify(self):
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            done = utcnow()
            db.add_all([
                JobMaster(  # needs AI read
                    linkedin_job_id='1', title='A',
                    job_url='u1', description_text='x' * 200,
                    requirements_enriched_at=done,
                ),
                JobMaster(  # already read
                    linkedin_job_id='2', title='B',
                    job_url='u2', description_text='x' * 200,
                    requirements_enriched_at=done, ai_read_at=done,
                ),
                JobMaster(  # no description stored
                    linkedin_job_id='3', title='C', job_url='u3',
                    requirements_enriched_at=done,
                ),
                JobMaster(  # enrich failed — dead URL, nothing to read
                    linkedin_job_id='4', title='D',
                    job_url='u4', description_text='x' * 200,
                    requirements_enriched_at=done, experience_label='enrich_failed',
                ),
                JobMaster(  # not yet detail-enriched
                    linkedin_job_id='5', title='E',
                    job_url='u5', description_text='x' * 200,
                ),
            ])
            db.commit()
            ids = pending_ai_read_ids(db, limit=10)
            rows = db.execute(
                select(JobMaster.linkedin_job_id).where(JobMaster.id.in_(ids))
            ).scalars().all()
            self.assertEqual(sorted(rows), ['1'])


if __name__ == '__main__':
    unittest.main()
