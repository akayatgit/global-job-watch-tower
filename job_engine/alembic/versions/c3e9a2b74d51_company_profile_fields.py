"""Add company logo / tagline / punchline / followers / employee size."""

from alembic import op
import sqlalchemy as sa


revision = 'c3e9a2b74d51'
down_revision = 'b2d8f1a93c40'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('companies', sa.Column('logo_url', sa.String(length=800), nullable=True))
    op.add_column('companies', sa.Column('tagline', sa.String(length=400), nullable=True))
    op.add_column('companies', sa.Column('punchline', sa.String(length=400), nullable=True))
    op.add_column('companies', sa.Column('about_text', sa.Text(), nullable=True))
    op.add_column('companies', sa.Column('follower_count', sa.Integer(), nullable=True))
    op.add_column('companies', sa.Column('employee_count_min', sa.Integer(), nullable=True))
    op.add_column('companies', sa.Column('employee_count_max', sa.Integer(), nullable=True))
    op.add_column(
        'companies',
        sa.Column('employee_count_label', sa.String(length=80), nullable=True),
    )
    op.add_column(
        'companies',
        sa.Column('profile_enriched_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'ix_companies_profile_enriched_at',
        'companies',
        ['profile_enriched_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_companies_profile_enriched_at', table_name='companies')
    op.drop_column('companies', 'profile_enriched_at')
    op.drop_column('companies', 'employee_count_label')
    op.drop_column('companies', 'employee_count_max')
    op.drop_column('companies', 'employee_count_min')
    op.drop_column('companies', 'follower_count')
    op.drop_column('companies', 'about_text')
    op.drop_column('companies', 'punchline')
    op.drop_column('companies', 'tagline')
    op.drop_column('companies', 'logo_url')
