"""RAG 檢索用的向量資料：課程與平台說明各自轉成向量，存在 pgvector 欄位。

課程的事實（價格、老師、時段）仍以 courses 為準；這張表只是為了「找得到」而存的衍生資料，
可以隨時用 scripts.index_course_embeddings 重建。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    cast,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from backend.models.base import Base

EMBEDDING_DIMENSION = 1024
SOURCE_COURSE = "course"
SOURCE_PLATFORM_GUIDE = "platform_guide"


class Vector(UserDefinedType):
    """pgvector 的 vector 型別，固定寫成 extensions.vector。

    Supabase 把擴充功能裝在 extensions schema；本機也照做。型別和運算子都寫完整名稱，
    本機（search_path 沒有 extensions）和 Supabase（有）才會有一樣的行為。
    """

    cache_ok = True

    def __init__(self, dimension: int = EMBEDDING_DIMENSION):
        self.dimension = dimension

    def get_col_spec(self, **kw):
        return f"extensions.vector({self.dimension})"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            return "[" + ",".join(repr(float(x)) for x in value) + "]"

        return process

    def bind_expression(self, bindvalue):
        # 參數以 '[0.1,0.2,…]' 文字送出，在 SQL 裡轉成 extensions.vector
        return cast(bindvalue, self)

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None:
                return None
            if isinstance(value, str):
                return [float(x) for x in value.strip("[]").split(",") if x]
            return [float(x) for x in value]

        return process


class RagDocument(Base):
    __tablename__ = "rag_documents"
    __table_args__ = (
        CheckConstraint(
            "(source_type = 'course' AND course_id IS NOT NULL AND source_key IS NULL)"
            " OR (source_type = 'platform_guide' AND course_id IS NULL AND source_key IS NOT NULL)",
            name="ck_rag_documents_source",
        ),
        Index(
            "uq_rag_documents_course",
            "course_id",
            "chunk_index",
            unique=True,
            postgresql_where="course_id IS NOT NULL",
        ),
        Index(
            "uq_rag_documents_source_key",
            "source_key",
            "chunk_index",
            unique=True,
            postgresql_where="source_key IS NOT NULL",
        ),
        Index(
            "ix_rag_documents_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "extensions.vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # 課程被刪除時向量跟著刪；平台說明沒有對應的資料列，用 source_key 標示是哪一段
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=True
    )
    source_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # bge-m3 在 Ollama 的 digest；和設定不同時這筆向量不使用
    model_version: Mapped[str] = mapped_column(String(160), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSION), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
