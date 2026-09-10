"""Prompt render reel (2026-09-10): the Instagram post asset is a video.

prompt_renders gains reel_key / reel_url (the composited 1080×1920 MP4:
title · AI clip in the hero box · storyboard | scrolling prompt) and
reel_error (why composition failed while the raw clip still exists).
"""

from alembic import op
import sqlalchemy as sa


revision = 'c8d4f0b23e56'
down_revision = 'b7c3e9a12d45'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('prompt_renders') as batch:
        batch.add_column(sa.Column('reel_key', sa.String(300), nullable=True))
        batch.add_column(sa.Column('reel_url', sa.String(1000), nullable=True))
        batch.add_column(sa.Column('reel_error', sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('prompt_renders') as batch:
        batch.drop_column('reel_error')
        batch.drop_column('reel_url')
        batch.drop_column('reel_key')
