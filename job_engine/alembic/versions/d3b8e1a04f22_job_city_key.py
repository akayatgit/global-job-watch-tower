"""Add city_key on jobs_master for city-wise hiring signals."""

from alembic import op
import sqlalchemy as sa


revision = 'd3b8e1a04f22'
down_revision = 'a7e2f91c4b30'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'jobs_master',
        sa.Column('city_key', sa.String(length=40), nullable=True),
    )
    op.create_index('ix_jobs_master_city_key', 'jobs_master', ['city_key'])
    op.create_index('ix_jobs_city_scraped', 'jobs_master', ['city_key', 'scraped_at'])


def downgrade() -> None:
    op.drop_index('ix_jobs_city_scraped', table_name='jobs_master')
    op.drop_index('ix_jobs_master_city_key', table_name='jobs_master')
    op.drop_column('jobs_master', 'city_key')
