"""Employer-stated skills / industry / salary (Ashok, 2026-08-15).

"Ai also needs to get qualifications, skills required, industry, and salary.
All if mentioned." Qualifications merge into the existing ``degrees`` list;
these three get their own columns:

- skills: AI-read list, each item grounded verbatim in the description.
- industry: LinkedIn's own criteria block first, AI-read fallback.
- salary_text: the verbatim stated salary snippet (never parsed guesses).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'f4b8d2e63a19'
down_revision = 'e2a7c9d418f3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs_master', sa.Column('skills', sa.JSON(), nullable=True))
    op.add_column('jobs_master', sa.Column('industry', sa.String(160), nullable=True))
    op.add_column('jobs_master', sa.Column('salary_text', sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs_master', 'salary_text')
    op.drop_column('jobs_master', 'industry')
    op.drop_column('jobs_master', 'skills')
