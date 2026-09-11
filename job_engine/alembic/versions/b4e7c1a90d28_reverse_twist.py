"""Reverse-prompt magic-pencil twist (2026-09-11).

After the original timestamped prompt and cut frames exist, one
imaginative line rewrites every beat and restyles the 14 stills
through text+image→image. Original columns stay untouched.
"""

from alembic import op
import sqlalchemy as sa


revision = 'b4e7c1a90d28'
down_revision = 'a3c9e1b72d04'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('reverse_prompts') as batch:
        batch.add_column(sa.Column('twist_text', sa.String(400), nullable=True))
        batch.add_column(sa.Column('twist_keyword', sa.String(60), nullable=True))
        batch.add_column(sa.Column('twist_prompt', sa.Text(), nullable=True))
        batch.add_column(sa.Column('twist_frames', sa.Text(), nullable=True))
        batch.add_column(sa.Column('twist_error', sa.Text(), nullable=True))
        batch.add_column(sa.Column('twist_status', sa.String(20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('reverse_prompts') as batch:
        batch.drop_column('twist_status')
        batch.drop_column('twist_error')
        batch.drop_column('twist_frames')
        batch.drop_column('twist_prompt')
        batch.drop_column('twist_keyword')
        batch.drop_column('twist_text')
