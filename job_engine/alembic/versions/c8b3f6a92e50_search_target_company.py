"""MNC-first collection: company-scoped searches (Ashok, 2026-08-14).

search_configs.target_company — pipe-separated company match needles; when
set, the search collects ONLY that company's jobs (see app/mnc_watchlist.py).
"""

from alembic import op
import sqlalchemy as sa


revision = 'c8b3f6a92e50'
down_revision = 'b6e4d2c95a10'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'search_configs',
        sa.Column('target_company', sa.String(300), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('search_configs', 'target_company')
