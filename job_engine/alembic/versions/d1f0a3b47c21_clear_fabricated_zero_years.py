"""Clear fabricated zero stated-years (live audit 2026-08-15).

Ashok's /topfreshers audit: 25/30 rows were jobs with NO stated years whose
LinkedIn "Entry level" tag made ``extract_requirements`` fabricate
``experience_min_years = 0`` — indistinguishable downstream from an employer
literally stating 0 years, so the mandatory fresher law passed them all.

The extractor no longer fabricates (band only, never stated years). This
data-only migration clears the fabrication already stored: exactly the rows
where the fabricating branch fired — min 0, no max, and the label the branch
copied from the tag ('Entry level' / 'Internship'). Genuinely stated years
keep numeric labels ('0 years', '0-1 years'…) and are untouched, as are
'Fresher / graduate' rows (explicit fresher wording in the text).

Downgrade is a no-op: fabricated evidence must never be restored.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'd1f0a3b47c21'
down_revision = 'c8b3f6a92e50'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE jobs_master SET experience_min_years = NULL "
            "WHERE experience_min_years = 0 "
            "AND experience_max_years IS NULL "
            "AND experience_label IN ('Entry level', 'Internship')"
        )
    )


def downgrade() -> None:
    pass
