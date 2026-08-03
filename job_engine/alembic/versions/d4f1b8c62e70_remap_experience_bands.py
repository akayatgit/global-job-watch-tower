"""Remap legacy experience_band labels to Fresher / 1-2 / 3-5 / 6-8 / 9-12 / 13+."""

from alembic import op


revision = 'd4f1b8c62e70'
down_revision = 'c3e9a2b74d51'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Best-effort remap of earlier enrich labels
    op.execute(
        "UPDATE jobs_master SET experience_band = 'Fresher' "
        "WHERE experience_band IN ('0-1 years')"
    )
    op.execute(
        "UPDATE jobs_master SET experience_band = '1-2 years' "
        "WHERE experience_band IN ('1-3 years')"
    )
    op.execute(
        "UPDATE jobs_master SET experience_band = '6-8 years' "
        "WHERE experience_band IN ('5-8 years')"
    )
    op.execute(
        "UPDATE jobs_master SET experience_band = '9-12 years' "
        "WHERE experience_band IN ('8-12 years')"
    )
    op.execute(
        "UPDATE jobs_master SET experience_band = '13+ years' "
        "WHERE experience_band IN ('12+ years')"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE jobs_master SET experience_band = '0-1 years' "
        "WHERE experience_band = 'Fresher'"
    )
    op.execute(
        "UPDATE jobs_master SET experience_band = '1-3 years' "
        "WHERE experience_band = '1-2 years'"
    )
    op.execute(
        "UPDATE jobs_master SET experience_band = '5-8 years' "
        "WHERE experience_band = '6-8 years'"
    )
    op.execute(
        "UPDATE jobs_master SET experience_band = '8-12 years' "
        "WHERE experience_band = '9-12 years'"
    )
    op.execute(
        "UPDATE jobs_master SET experience_band = '12+ years' "
        "WHERE experience_band = '13+ years'"
    )
