"""RAG 向量改存 pgvector：新增 rag_documents（extensions.vector(1024) ＋ HNSW 餘弦索引）。

擴充功能裝在 extensions schema：Supabase 本來就這樣放，本機也照做，兩邊的備份與 SQL 才一致。
向量不從 course_embeddings 搬過來，由 scripts.index_course_embeddings 重新產生
（課程內容的雜湊方式和舊表相同，但要確認每筆都是目前的 bge-m3 版本）。
course_embeddings 先保留，下一個版本確認沒有程式在讀再刪。

Revision ID: 024_pgvector_rag
Revises: 023_course_delivery_mode
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "024_pgvector_rag"
down_revision = "023_course_delivery_mode"
branch_labels = None
depends_on = None


class _Vector1024(sa.types.UserDefinedType):
    """只給建表用；Migration 不依賴應用程式的 Model 程式碼。"""

    cache_ok = True

    def get_col_spec(self, **kw):
        return "extensions.vector(1024)"


def upgrade():
    op.execute("CREATE SCHEMA IF NOT EXISTS extensions")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions")
    op.create_table(
        "rag_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("source_key", sa.String(120), nullable=True),
        sa.Column("chunk_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(160), nullable=False),
        sa.Column("embedding", _Vector1024(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "(source_type = 'course' AND course_id IS NOT NULL AND source_key IS NULL)"
            " OR (source_type = 'platform_guide' AND course_id IS NULL AND source_key IS NOT NULL)",
            name="ck_rag_documents_source",
        ),
    )
    op.create_index(
        "uq_rag_documents_course",
        "rag_documents",
        ["course_id", "chunk_index"],
        unique=True,
        postgresql_where=sa.text("course_id IS NOT NULL"),
    )
    op.create_index(
        "uq_rag_documents_source_key",
        "rag_documents",
        ["source_key", "chunk_index"],
        unique=True,
        postgresql_where=sa.text("source_key IS NOT NULL"),
    )
    # 餘弦距離的近似最近鄰索引；資料少時查詢計畫可能直接全表掃描，結果一樣
    op.execute(
        "CREATE INDEX ix_rag_documents_embedding ON rag_documents "
        "USING hnsw (embedding extensions.vector_cosine_ops)"
    )


def downgrade():
    op.drop_table("rag_documents")
    # 不移除 vector 擴充功能：Supabase 上可能有其他用途，留著也不影響舊版程式
