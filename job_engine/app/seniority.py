"""Title-level seniority evidence — the fresher-truthfulness veto.

Live incident (2026-08-14): "Omniverse – Software Engineer II" at Deloitte
(detail page: Bachelor's + 3–6 years) was shown to guests as "Fresher".
LinkedIn's own Internship/Entry search filter (f_E=1,2) mislabels senior
roles constantly, and the silence-stamp in ``card_requirements`` trusted it
unconditionally. The title said "II" the whole time — this module is the
single place that reads seniority evidence out of a job title.

The regexes use ``(^|[^a-z])token([^a-z]|$)`` instead of ``\\b`` (same trick
as ``ROLE_FAMILY_REGEX``) so the exact same pattern string works in Python
``re`` and in Postgres ``~*`` (where ``\\b`` means backspace).

Law: explicit fresher wording in the title (intern / trainee / graduate /
fresher / junior / apprentice) always defeats the veto — "Management
Trainee" and "Graduate Engineer Trainee" are employer-declared fresher
roles and must never be filtered out of fresher results.
"""

from __future__ import annotations

import re

# Explicit fresher evidence in the title — defeats any seniority signal.
FRESHER_TITLE_REGEX = (
    r'(?i)(^|[^a-z])(?:'
    r'interns?|internships?|trainees?|graduates?|freshers?|'
    r'apprentices?|apprenticeships?|juniors?|jr\.?'
    r')([^a-z]|$)'
)

# Seniority signals a fresher job title cannot carry. Kept deliberately
# conservative: "consultant", "associate", "analyst", "specialist" alone are
# NOT seniority (Big-4 entry roles use them); bare "lead" is only seniority
# in role-shaped phrases so "Lead Generation Executive" survives.
SENIORITY_TITLE_REGEX = (
    r'(?i)(^|[^a-z])(?:'
    r'seniors?|snr|sr\.?|'
    r'principal|architect|managers?|head|director|'
    r'vp|vice[\s-]+president|president|chief|'
    r'cto|cio|ciso|cfo|ceo|coo|'
    r'experienced|experts?|'
    r'mid[\s-]?senior|'
    r'staff\s+(?:[a-z]+\s+)?engineer|'
    r'ii|iii|iv|'
    r'(?:team|tech|technical|project|module|track|delivery|engineering|'
    r'development|qa|test|design|data|security)[\s-]+lead|'
    r'lead\s+(?:engineer|developer|programmer|analyst|consultant|architect|'
    r'designer|scientist|auditor|recruiter)'
    r')([^a-z]|$)'
)

FRESHER_TITLE_PATTERN = re.compile(FRESHER_TITLE_REGEX)
SENIORITY_TITLE_PATTERN = re.compile(SENIORITY_TITLE_REGEX)

# The label card_requirements stamps when LinkedIn's Internship/Entry filter
# is the ONLY fresher evidence (nothing stated by the employer). /topfreshers
# must never treat this inferred label as an explicit fresher statement.
FRESHER_TRACK_SILENCE_LABEL = 'Fresher track (LinkedIn Internship/Entry)'

# Explicitly-declared fresher / zero-experience wording. Deliberately tighter
# than FRESHER_TITLE_REGEX: "Junior" or an internship tag is early-career
# evidence, but only the employer literally saying fresher / fresh graduate /
# no experience / 0 years makes a row a /topfreshers video gem. The wrapper
# uses [^a-z0-9] so "10 years" can never match the "0 years" alternative and
# "refresher" can never match "fresher".
EXPLICIT_FRESHER_REGEX = (
    r'(?i)(^|[^a-z0-9])(?:'
    r'freshers?|fresh\s+graduates?|'
    r'no\s+(?:prior\s+|work\s+)?experience|'
    r'zero\s+experience|'
    r'0\s*(?:-|–|to\s+)?\s*\d*\s*\+?\s*(?:years?|yrs?)'
    r')([^a-z]|$)'
)
EXPLICIT_FRESHER_PATTERN = re.compile(EXPLICIT_FRESHER_REGEX)


def title_seniority_veto(title: str | None) -> bool:
    """True when the title itself contradicts a Fresher label.

    Used to (a) block the fresher-track silence stamp at insert, (b) exclude
    unverified rows from fresher search results, until the detail page
    verifies the real years. Explicit fresher wording always wins.
    """
    text = (title or '').strip()
    if not text:
        return False
    if FRESHER_TITLE_PATTERN.search(text):
        return False
    return bool(SENIORITY_TITLE_PATTERN.search(text))


def fresher_title_safe_clause():
    """SQLAlchemy WHERE fragment keeping only rows a fresher may see:
    title carries no seniority signal, or carries explicit fresher wording.
    """
    from sqlalchemy import or_

    from app.models import JobMaster

    seniority = JobMaster.title.op('~*')(
        SENIORITY_TITLE_REGEX.removeprefix('(?i)')
    )
    fresher_words = JobMaster.title.op('~*')(
        FRESHER_TITLE_REGEX.removeprefix('(?i)')
    )
    return or_(~seniority, fresher_words)


def explicit_fresher_clause():
    """SQLAlchemy WHERE fragment for /topfreshers gems: the employer
    explicitly said fresher / 0 experience — in the title, in the card
    details text, as a parsed minimum of 0 stated years, or as a stated
    fresher experience label. LinkedIn's Internship/Entry silence-stamp
    label never qualifies (that is inference, not a statement).
    """
    from sqlalchemy import and_, or_

    from app.models import JobMaster

    pg = EXPLICIT_FRESHER_REGEX.removeprefix('(?i)')
    stated_fresher_label = and_(
        JobMaster.experience_label.op('~*')('(^|[^a-z])freshers?([^a-z]|$)'),
        JobMaster.experience_label != FRESHER_TRACK_SILENCE_LABEL,
    )
    return or_(
        JobMaster.title.op('~*')(pg),
        JobMaster.raw_text.op('~*')(pg),
        JobMaster.experience_min_years == 0,
        stated_fresher_label,
    )
