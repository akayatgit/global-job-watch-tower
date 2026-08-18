"""GTM role allowlist — only these titles are stored from MNC company searches.

Ashok (2026-08-18): collect complete data on a focused set of entry/trainee/
intern/analyst roles at watched giants — not every LinkedIn Entry-tagged
title. Matching is phrase-based on the job TITLE (case-insensitive, flexible
whitespace/hyphens). Card marketing text never qualifies a role.
"""

from __future__ import annotations

import re

# Canonical phrases Ashok named. Duplicates (Data analyst / Data Analyst /
# Data Analyst Trainee listed twice) collapse via the set used to build
# patterns. Bare "Apprentice" is intentional — any apprentice title is in.
TARGET_ROLE_PHRASES: tuple[str, ...] = (
    'Software Developer Trainee',
    'Junior Software Developer',
    'Software Development Intern',
    'Data Analyst Trainee',
    'Business Analyst Intern',
    'QA Automation Engineer',
    'QA Testing Intern',
    'Cloud Support Engineer',
    'Technical Support Intern',
    'Digital Marketing Executive',
    'Digital Marketing Intern',
    'Customer Support Associate',
    'Customer Support Intern',
    'Finance Trainee',
    'Finance Intern',
    'Operations Management Intern',
    'Data Analyst',
    'Junior Data Analyst',
    'Associate Data Analyst',
    'Data Analysis Intern',
    'Business Intelligence Analyst',
    'BI Analyst Trainee',
    'BI Intern',
    'Analytics Engineer',
    'Analytics Trainee',
    'Data Operations Analyst',
    'Data Operations Trainee',
    'Data Operations Intern',
    'Junior Data Engineer',
    'Data Engineering Intern',
    'Reporting Analyst',
    'Junior Quantitative Analyst',
    'Apprentice',
)


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    """Word-boundary phrase match; spaces in the phrase also accept -/_."""
    parts = [re.escape(p) for p in phrase.lower().split() if p]
    body = r'[\s\-_\/]+'.join(parts)
    return re.compile(rf'(^|[^a-z0-9]){body}([^a-z0-9]|$)', re.IGNORECASE)


# Longer phrases first so "Data Analyst Trainee" wins inspection order over
# "Data Analyst" when debugging; match itself is ANY-of.
_TARGET_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    _phrase_pattern(p)
    for p in sorted(set(TARGET_ROLE_PHRASES), key=lambda s: (-len(s), s.lower()))
)


def title_matches_target_role(title: str | None) -> bool:
    """True when the job title carries one of the GTM allowlisted phrases."""
    text = (title or '').strip()
    if not text:
        return False
    return any(p.search(text) for p in _TARGET_PATTERNS)


def target_role_sql_clause():
    """SQLAlchemy OR of title ~* patterns — for serving filters if needed."""
    from sqlalchemy import or_

    from app.models import JobMaster

    clauses = []
    for phrase in sorted(set(TARGET_ROLE_PHRASES), key=lambda s: (-len(s), s.lower())):
        parts = [re.escape(p) for p in phrase.lower().split() if p]
        body = r'[\s\-_\/]+'.join(parts)
        # Postgres ~* : drop the (?i) flag; case-insensitive op handles it.
        clauses.append(JobMaster.title.op('~*')(rf'(^|[^a-z0-9]){body}([^a-z0-9]|$)'))
    return or_(*clauses)
