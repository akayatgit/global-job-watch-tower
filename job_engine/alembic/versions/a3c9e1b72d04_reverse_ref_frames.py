"""Reverse-prompt cut-reference frames (2026-09-11).

The vision model lists hard cuts; we strip that array from the stored
prompt and grab ~14 JPEGs at those timestamps for Ashok to attach when
he recreates the clip. Not the 6-frame reel storyboard.
"""

from alembic import op
import sqlalchemy as sa


revision = 'a3c9e1b72d04'
down_revision = 'f2c4d6e8a910'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('reverse_prompts') as batch:
        batch.add_column(sa.Column('ref_frames', sa.Text(), nullable=True))
        batch.add_column(sa.Column('ref_error', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('reverse_prompts') as batch:
        batch.drop_column('ref_error')
        batch.drop_column('ref_frames')
