"""GTM role×city hunting searches: LinkedIn f_WT workplace filter.

search_configs.work_type_filter — LinkedIn f_WT codes (1=on-site, 2=remote,
3=hybrid). The GTM Remote hunting search uses '2' so a whole search's pages
are spent on remote fresher roles instead of an India-wide ranking.
"""

from alembic import op
import sqlalchemy as sa


revision = 'a9d5e3f81c60'
down_revision = 'f4b8d2e63a19'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'search_configs',
        sa.Column('work_type_filter', sa.String(10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('search_configs', 'work_type_filter')
