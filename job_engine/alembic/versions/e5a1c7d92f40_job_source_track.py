"""Store immutable search-track provenance on jobs."""

from alembic import op
import sqlalchemy as sa


revision = 'e5a1c7d92f40'
down_revision = 'd4f1b8c62e70'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'jobs_master',
        sa.Column('source_track', sa.String(length=20), nullable=True),
    )
    op.create_index('ix_jobs_master_source_track', 'jobs_master', ['source_track'])
    # Best available historical provenance. Future inserts copy the track at
    # capture time, so later SearchConfig edits cannot rewrite job history.
    op.execute(
        """
        UPDATE jobs_master AS j
        SET source_track = sc.track
        FROM search_configs AS sc
        WHERE j.search_config_id = sc.id
          AND j.source_track IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index('ix_jobs_master_source_track', table_name='jobs_master')
    op.drop_column('jobs_master', 'source_track')
