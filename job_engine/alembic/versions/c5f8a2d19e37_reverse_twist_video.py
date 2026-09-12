"""Reverse-prompt Gemini Omni twist video (2026-09-12).

After twisted stills exist, google/gemini-omni-1.1 motion-transfers
the original clip onto those frames. Stills stay if the video fails.
"""

from alembic import op
import sqlalchemy as sa


revision = 'c5f8a2d19e37'
down_revision = 'b4e7c1a90d28'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('reverse_prompts') as batch:
        batch.add_column(sa.Column('twist_video_key', sa.String(300), nullable=True))
        batch.add_column(sa.Column('twist_video_url', sa.String(1000), nullable=True))
        batch.add_column(sa.Column('twist_video_error', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('reverse_prompts') as batch:
        batch.drop_column('twist_video_error')
        batch.drop_column('twist_video_url')
        batch.drop_column('twist_video_key')
