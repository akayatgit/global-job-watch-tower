"""Prompt Tower pivot (2026-09-09): jobs are now prompts.

Three tables carry the new product:
- video_prompts      — every collected AI video prompt with provenance,
                       deterministic + Hermes scores, RAG embedding,
                       owner rating and Instagram performance.
- prompt_shortlists  — the top-10 of each UTC day (what Ashok receives).
- prompt_renders     — approved prompt + product image → AI video jobs.

Job tables are untouched: the jobs stack sleeps behind TOWER_MODE, it is
not deleted (source-safety law).
"""

from alembic import op
import sqlalchemy as sa


revision = 'b7c3e9a12d45'
down_revision = 'a9d5e3f81c60'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'video_prompts',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer, 'sqlite'), primary_key=True),
        sa.Column('fingerprint', sa.String(40), nullable=False),
        sa.Column('text', sa.Text, nullable=False),
        sa.Column('title', sa.String(300), nullable=True),
        sa.Column('source', sa.String(40), nullable=False),
        sa.Column('source_url', sa.String(1000), nullable=True),
        sa.Column('author', sa.String(200), nullable=True),
        sa.Column('source_posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('collected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('model_hint', sa.String(40), nullable=True),
        sa.Column('category', sa.String(60), nullable=True),
        sa.Column('heuristic_score', sa.Float, nullable=True),
        sa.Column('ai_detail', sa.Float, nullable=True),
        sa.Column('ai_flow', sa.Float, nullable=True),
        sa.Column('ai_score', sa.Float, nullable=True),
        sa.Column('ai_reasons', sa.JSON, nullable=True),
        sa.Column('final_score', sa.Float, nullable=True),
        sa.Column('baseline_mean', sa.Float, nullable=True),
        sa.Column('baseline_std', sa.Float, nullable=True),
        sa.Column('is_outlier', sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column('embedding', sa.JSON, nullable=True),
        sa.Column('scored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='new'),
        sa.Column('rating', sa.Integer, nullable=True),
        sa.Column('performance', sa.JSON, nullable=True),
        sa.Column('performance_score', sa.Float, nullable=True),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('exemplar', sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index('ix_video_prompts_fingerprint', 'video_prompts', ['fingerprint'], unique=True)
    op.create_index('ix_video_prompts_source', 'video_prompts', ['source'])
    op.create_index('ix_video_prompts_collected_at', 'video_prompts', ['collected_at'])
    op.create_index('ix_video_prompts_category', 'video_prompts', ['category'])
    op.create_index('ix_video_prompts_final_score', 'video_prompts', ['final_score'])
    op.create_index('ix_video_prompts_is_outlier', 'video_prompts', ['is_outlier'])
    op.create_index('ix_video_prompts_status', 'video_prompts', ['status'])
    op.create_index('ix_video_prompts_performance_score', 'video_prompts', ['performance_score'])
    op.create_index('ix_video_prompts_exemplar', 'video_prompts', ['exemplar'])

    op.create_table(
        'prompt_shortlists',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer, 'sqlite'), primary_key=True),
        sa.Column('day', sa.Date, nullable=False),
        sa.Column('rank', sa.Integer, nullable=False),
        sa.Column('prompt_id', sa.BigInteger().with_variant(sa.Integer, 'sqlite'),
                  sa.ForeignKey('video_prompts.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_prompt_shortlists_day', 'prompt_shortlists', ['day'])
    op.create_index('ix_prompt_shortlists_prompt_id', 'prompt_shortlists', ['prompt_id'])
    op.create_index('ux_prompt_shortlists_day_rank', 'prompt_shortlists', ['day', 'rank'], unique=True)

    op.create_table(
        'prompt_renders',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer, 'sqlite'), primary_key=True),
        sa.Column('prompt_id', sa.BigInteger().with_variant(sa.Integer, 'sqlite'),
                  sa.ForeignKey('video_prompts.id'), nullable=False),
        sa.Column('chat_id', sa.String(40), nullable=True),
        sa.Column('product_image_key', sa.String(300), nullable=True),
        sa.Column('card_image_key', sa.String(300), nullable=True),
        sa.Column('video_key', sa.String(300), nullable=True),
        sa.Column('video_url', sa.String(1000), nullable=True),
        sa.Column('model', sa.String(200), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='queued'),
        sa.Column('error', sa.Text, nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_prompt_renders_prompt_id', 'prompt_renders', ['prompt_id'])
    op.create_index('ix_prompt_renders_status', 'prompt_renders', ['status'])


def downgrade() -> None:
    op.drop_table('prompt_renders')
    op.drop_table('prompt_shortlists')
    op.drop_table('video_prompts')
