"""Fresher truthfulness backfill: clear silence-stamped 'Fresher' bands on
seniority-titled jobs (live incident 2026-08-14 — "Software Engineer II" at
Deloitte shown to guests as Fresher).

Only rows whose Fresher band came from the fresher-track silence stamp are
touched: detail-verified rows (requirements_enriched_at set) and rows with
stated years (experience_min_years set) keep their evidence. Patterns are a
frozen copy of app/seniority.py at the time of this migration.
"""

from alembic import op


revision = 'b6e4d2c95a10'
down_revision = 'e5a1c7d92f40'
branch_labels = None
depends_on = None

SENIORITY_TITLE_SQL = (
    r'(^|[^a-z])(?:'
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
FRESHER_TITLE_SQL = (
    r'(^|[^a-z])(?:'
    r'interns?|internships?|trainees?|graduates?|freshers?|'
    r'apprentices?|apprenticeships?|juniors?|jr\.?'
    r')([^a-z]|$)'
)


def upgrade() -> None:
    # exec_driver_sql, NOT op.execute: op.execute wraps the string in
    # sqlalchemy.text(), which read every regex "(?:" group as a bind
    # parameter (":seniors", ":team", …) and aborted with
    # InvalidRequestError — this single migration blocked ALL ThinkPad
    # deploys on 2026-08-14 until fixed. Driver-level execution passes the
    # SQL to psycopg2 verbatim.
    op.get_bind().exec_driver_sql(
        "UPDATE jobs_master "
        "SET experience_band = NULL, "
        "    experience_label = 'Seniority in title — pending verification' "
        "WHERE experience_band = 'Fresher' "
        "  AND requirements_enriched_at IS NULL "
        "  AND experience_min_years IS NULL "
        f"  AND title ~* '{SENIORITY_TITLE_SQL}' "
        f"  AND NOT (title ~* '{FRESHER_TITLE_SQL}')"
    )


def downgrade() -> None:
    # Data-only fix; restoring the dishonest 'Fresher' stamp on seniority
    # titles is never desirable. The pending-verification label marks the
    # affected rows if a manual audit is ever needed.
    pass
