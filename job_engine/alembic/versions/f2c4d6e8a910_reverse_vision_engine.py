"""Reverse prompt vision engine pick (2026-09-11).

After the header title, Telegram offers Gemini · GPT-6 Astra · Claude Fable 5.
Stored as vision_engine (gemini | astra | fable); `model` stays the API id
that actually wrote the prompt.
"""

from alembic import op
import sqlalchemy as sa


revision = 'f2c4d6e8a910'
down_revision = 'e1b2c3d4f506'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('reverse_prompts') as batch:
        batch.add_column(sa.Column('vision_engine', sa.String(20), nullable=False, server_default='gemini'))


def downgrade() -> None:
    with op.batch_alter_table('reverse_prompts') as batch:
        batch.drop_column('vision_engine')
