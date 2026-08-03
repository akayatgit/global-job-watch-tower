"""Add experience / degree / cert / domain requirement fields on jobs."""

from alembic import op
import sqlalchemy as sa


revision = 'f9c2d4e6a810'
down_revision = 'd3b8e1a04f22'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'jobs_master',
        sa.Column('experience_min_years', sa.Float(), nullable=True),
    )
    op.add_column(
        'jobs_master',
        sa.Column('experience_max_years', sa.Float(), nullable=True),
    )
    op.add_column(
        'jobs_master',
        sa.Column('experience_label', sa.String(length=120), nullable=True),
    )
    op.add_column(
        'jobs_master',
        sa.Column('experience_band', sa.String(length=40), nullable=True),
    )
    op.add_column(
        'jobs_master',
        sa.Column('seniority_level', sa.String(length=80), nullable=True),
    )
    op.add_column(
        'jobs_master',
        sa.Column('degrees', sa.JSON(), nullable=True),
    )
    op.add_column(
        'jobs_master',
        sa.Column('certifications', sa.JSON(), nullable=True),
    )
    op.add_column(
        'jobs_master',
        sa.Column('domains', sa.JSON(), nullable=True),
    )
    op.add_column(
        'jobs_master',
        sa.Column('description_text', sa.Text(), nullable=True),
    )
    op.add_column(
        'jobs_master',
        sa.Column(
            'requirements_enriched_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        'ix_jobs_master_experience_band',
        'jobs_master',
        ['experience_band'],
    )
    op.create_index(
        'ix_jobs_master_requirements_enriched_at',
        'jobs_master',
        ['requirements_enriched_at'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_jobs_master_requirements_enriched_at', table_name='jobs_master',
    )
    op.drop_index('ix_jobs_master_experience_band', table_name='jobs_master')
    op.drop_column('jobs_master', 'requirements_enriched_at')
    op.drop_column('jobs_master', 'description_text')
    op.drop_column('jobs_master', 'domains')
    op.drop_column('jobs_master', 'certifications')
    op.drop_column('jobs_master', 'degrees')
    op.drop_column('jobs_master', 'seniority_level')
    op.drop_column('jobs_master', 'experience_band')
    op.drop_column('jobs_master', 'experience_label')
    op.drop_column('jobs_master', 'experience_max_years')
    op.drop_column('jobs_master', 'experience_min_years')
