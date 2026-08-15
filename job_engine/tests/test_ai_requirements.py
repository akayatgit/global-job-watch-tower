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
    'of experience in analytics.'
)

SENIOR_DESC = (
    'We are looking for an experienced engineer. '
    'A minimum of 5 years of experience with Zscaler is required. '
    'This role is not suitable for freshers.'
)


def reply(experience=None, fresher=None) -> str:
    return json.dumps({
        'experience': experience or {'min_years': None, 'max_years': None, 'quote': None},
        'fresher_statement': fresher or {'present': False, 'quote': None},
    })


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
