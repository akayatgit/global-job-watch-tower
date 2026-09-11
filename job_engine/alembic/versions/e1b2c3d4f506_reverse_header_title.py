"""Reverse prompt header title (2026-09-11).

Ashok types the cinematic header after the Instagram / Pinterest URL
("CINEMATIC AI AD"). The footer is hardcoded in the reel composer.
"""

from alembic import op
import sqlalchemy as sa


revision = 'e1b2c3d4f506'
down_revision = 'd9e5a1c47f02'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('reverse_prompts') as batch:
        batch.add_column(sa.Column('header_title', sa.String(120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('reverse_prompts') as batch:
        batch.drop_column('header_title')
