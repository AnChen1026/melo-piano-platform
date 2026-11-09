"""AI 找課的推薦問題：30 句驗證過的開場問題，對話是空的時候隨機給 3 句。

每句記錄最後一次驗證的結果；驗證沒過的 is_active 為 false，不會出現在網站上。
內容由 scripts/chat_starters.py 從 scripts/data/chat_starters.json 寫入。

Revision ID: 025_course_chat_starters
Revises: 024_pgvector_rag
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "025_course_chat_starters"
down_revision = "024_pgvector_rag"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "course_chat_starters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("text", sa.String(60), nullable=False, unique=True),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_model_version", sa.String(160), nullable=True),
        sa.Column("top_score", sa.Float, nullable=True),
        sa.Column("check_note", sa.String(300), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "category IN ('course_search', 'criteria', 'platform_howto')", name="ck_course_chat_starters_category"
        ),
    )
    op.create_index("ix_course_chat_starters_active", "course_chat_starters", ["is_active"])


def downgrade():
    op.drop_table("course_chat_starters")
