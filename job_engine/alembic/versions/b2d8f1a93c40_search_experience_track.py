"""Add experience_filter + track on search_configs (fresher vs signal)."""

from alembic import op
import sqlalchemy as sa


revision = 'b2d8f1a93c40'
down_revision = 'f9c2d4e6a810'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'search_configs',
        sa.Column('experience_filter', sa.String(length=40), nullable=True),
    )
    op.add_column(
        'search_configs',
        sa.Column('track', sa.String(length=20), nullable=False, server_default='fresher'),
    )
    op.create_index('ix_search_configs_track', 'search_configs', ['track'])
    # Existing catalogue was fresher-intent but unfiltered — leave filter null
    # until seed rewrites Track A to "1,2". Track defaults to fresher.


def downgrade() -> None:
    op.drop_index('ix_search_configs_track', table_name='search_configs')
    op.drop_column('search_configs', 'track')
    op.drop_column('search_configs', 'experience_filter')
