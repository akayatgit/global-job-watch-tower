"""Reverse / twist per-step timings (2026-09-12).

Log started_at plus each generation step so we can cut the wait.
"""

from alembic import op
import sqlalchemy as sa


revision = 'd6a1c4e80b29'
down_revision = 'c5f8a2d19e37'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('reverse_prompts') as batch:
        batch.add_column(sa.Column('timings', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('reverse_prompts') as batch:
        batch.drop_column('timings')
