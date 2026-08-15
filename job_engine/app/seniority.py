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

# The MANDATORY fresher law (Ashok, 2026-08-14 21:02): a servable job must
# literally say "fresher" (or "fresh graduate") in its TITLE, or its stated
# years-of-experience must be 0–1. Nothing else counts: card-text marketing
# ("freshers welcome" in a 3–6-years job), labels, and LinkedIn's Entry tag
# were all letting 9/10 non-fresher rows through /topfreshers. The wrapper
# uses [^a-z0-9] so "refresher" can never match "fresher".
MANDATORY_FRESHER_TITLE_REGEX = (
    r'(?i)(^|[^a-z0-9])(?:freshers?|fresh\s+graduates?)([^a-z]|$)'
)
MANDATORY_FRESHER_TITLE_PATTERN = re.compile(MANDATORY_FRESHER_TITLE_REGEX)

# Stated minimum years a fresher can honestly be asked for: 0 or 1.
MANDATORY_FRESHER_MAX_MIN_YEARS = 1.0


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


def is_mandatory_fresher(
    title: str | None,
    experience_min_years: float | None,
    experience_max_years: float | None = None,
    ai_fresher_verdict: bool | None = None,
) -> bool:
    """Python twin of ``mandatory_fresher_clause`` — one law, two runtimes.

    Qualifies when the title carries no seniority signal AND:
    - stated years-of-experience exist and the WHOLE range is 0–1
      ("1-3 years" is NOT a fresher job — live audit 2026-08-15 showed five
      Wipro "1-3 years" rows passing a min-only check), OR
    - years are absent and the title literally says fresher/fresh graduate, OR
    - years are absent and the AI description reading found an explicit,
      quote-grounded fresher statement (app/ai_requirements.py — the quote
      must exist verbatim in the employer's own description text).
    A seniority-signalled title (Senior/L2/II/Lead…) vetoes the row even
    when stated years pass — "Senior Engineer" was row #1 of the bad list.
    Stated years always outrank the AI verdict: a description stating 3–6
    years excludes the row no matter what the model concluded.
    """
    if title_seniority_veto(title):
        return False
    if experience_min_years is not None:
        return (
            0 <= experience_min_years <= MANDATORY_FRESHER_MAX_MIN_YEARS
            and (
                experience_max_years is None
                or experience_max_years <= MANDATORY_FRESHER_MAX_MIN_YEARS
            )
        )
    if ai_fresher_verdict is True:
        return True
    return bool(MANDATORY_FRESHER_TITLE_PATTERN.search((title or '').strip()))


def mandatory_fresher_clause():
    """SQLAlchemy WHERE fragment of the mandatory fresher law: the whole
    stated years range is 0–1, or fresher literally in the title with no
    stated years at all — and the title never carries a seniority signal.
    LinkedIn's Entry tag / silence-stamp label are never evidence (they
    don't touch title or stated years — and since the 2026-08-15 fix the
    extractor no longer fabricates stated years from them either).
    """
    from sqlalchemy import and_, or_

    from app.models import JobMaster

    stated_0_1 = and_(
        JobMaster.experience_min_years.is_not(None),
        JobMaster.experience_min_years >= 0,
        JobMaster.experience_min_years <= MANDATORY_FRESHER_MAX_MIN_YEARS,
        or_(
            JobMaster.experience_max_years.is_(None),
            JobMaster.experience_max_years <= MANDATORY_FRESHER_MAX_MIN_YEARS,
        ),
    )
    fresher_titled_uncontradicted = and_(
        JobMaster.title.op('~*')(
            MANDATORY_FRESHER_TITLE_REGEX.removeprefix('(?i)')
        ),
        JobMaster.experience_min_years.is_(None),
    )
    ai_statement_uncontradicted = and_(
        JobMaster.ai_fresher_verdict.is_(True),
        JobMaster.experience_min_years.is_(None),
    )
    return and_(
        or_(
            stated_0_1,
            fresher_titled_uncontradicted,
            ai_statement_uncontradicted,
        ),
        fresher_title_safe_clause(),
    )
