"""company watchlist columns

Revision ID: c4f8a91b2e10
Revises: 1be3c38600c1
Create Date: 2026-08-01 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c4f8a91b2e10'
down_revision = '1be3c38600c1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'companies',
        sa.Column('watched', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'companies',
        sa.Column('watched_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f('ix_companies_watched'), 'companies', ['watched'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_companies_watched'), table_name='companies')
    op.drop_column('companies', 'watched_at')
    op.drop_column('companies', 'watched')
