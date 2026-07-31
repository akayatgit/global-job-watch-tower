"""Add tower_events for Tower Health pulse metrics."""

from alembic import op
import sqlalchemy as sa


revision = 'a7e2f91c4b30'
down_revision = 'c4f8a91b2e10'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'tower_events',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('kind', sa.String(length=40), nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=True),
        sa.Column('detail', sa.String(length=1000), nullable=False, server_default=''),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_tower_events_ts', 'tower_events', ['ts'])
    op.create_index('ix_tower_events_kind', 'tower_events', ['kind'])
    op.create_index('ix_tower_events_run_id', 'tower_events', ['run_id'])


def downgrade() -> None:
    op.drop_index('ix_tower_events_run_id', table_name='tower_events')
    op.drop_index('ix_tower_events_kind', table_name='tower_events')
    op.drop_index('ix_tower_events_ts', table_name='tower_events')
    op.drop_table('tower_events')
