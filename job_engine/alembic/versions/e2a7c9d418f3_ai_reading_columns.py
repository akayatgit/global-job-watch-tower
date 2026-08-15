"""AI description-reading columns (Ashok, 2026-08-15).

"Use AI to understand detailed descriptions of jobs" — the local Ollama
model reads stored ``description_text`` and reports employer statements
about experience, grounded by verbatim quotes (app/ai_requirements.py).

- ai_fresher_verdict: TRUE = employer explicitly welcomes freshers,
  FALSE = description read, no such statement, NULL = not read yet.
- ai_fresher_evidence: the verbatim sentence backing the verdict/years.
- ai_read_at: when the reading happened (NULL rows are backfilled by beat).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'e2a7c9d418f3'
down_revision = 'd1f0a3b47c21'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs_master', sa.Column('ai_fresher_verdict', sa.Boolean(), nullable=True))
    op.add_column('jobs_master', sa.Column('ai_fresher_evidence', sa.String(400), nullable=True))
    op.add_column('jobs_master', sa.Column('ai_read_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs_master', 'ai_read_at')
    op.drop_column('jobs_master', 'ai_fresher_evidence')
    op.drop_column('jobs_master', 'ai_fresher_verdict')
