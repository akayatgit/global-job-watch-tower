"""Reverse prompts (2026-09-10): Instagram / Pinterest video → Gemini
timestamped prompt → reel.

One row per /igtovid · /pintovid run: where the clip came from, the stored
clip, what the vision model wrote (verbatim), the catalogue prompt it
became, and the composed reel (or why composition failed).
"""

from alembic import op
import sqlalchemy as sa


revision = 'd9e5a1c47f02'
down_revision = 'c8d4f0b23e56'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'reverse_prompts',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer, 'sqlite'), primary_key=True),
        sa.Column('chat_id', sa.String(40), nullable=True),
        sa.Column('platform', sa.String(20), nullable=False, server_default='upload'),
        sa.Column('source_url', sa.String(1000), nullable=True),
        sa.Column('media_url', sa.String(2000), nullable=True),
        sa.Column('video_key', sa.String(300), nullable=True),
        sa.Column('video_url', sa.String(1000), nullable=True),
        sa.Column('duration_s', sa.Float, nullable=True),
        sa.Column('keyword', sa.String(60), nullable=True),
        sa.Column('prompt_text', sa.Text, nullable=True),
        sa.Column('model', sa.String(200), nullable=True),
        sa.Column('prompt_id', sa.BigInteger().with_variant(sa.Integer, 'sqlite'),
                  sa.ForeignKey('video_prompts.id'), nullable=True),
        sa.Column('reel_key', sa.String(300), nullable=True),
        sa.Column('reel_url', sa.String(1000), nullable=True),
        sa.Column('reel_error', sa.Text, nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='queued'),
        sa.Column('error', sa.Text, nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_reverse_prompts_status', 'reverse_prompts', ['status'])


def downgrade() -> None:
    op.drop_index('ix_reverse_prompts_status', table_name='reverse_prompts')
    op.drop_table('reverse_prompts')
