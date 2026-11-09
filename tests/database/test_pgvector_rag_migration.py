"""Migration contract for the pgvector RAG table."""

from __future__ import annotations

import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text


UPSTREAM_REVISION = "023_course_delivery_mode"
PGVECTOR_REVISION = "024_pgvector_rag"


def _vector(index: int) -> str:
    values = ["0"] * 1024
    values[index] = "1"
    return "[" + ",".join(values) + "]"


def test_024_creates_vector_table_in_extensions_schema(migration_database: tuple[Config, Engine]) -> None:
    config, engine = migration_database
    command.upgrade(config, UPSTREAM_REVISION)
    command.upgrade(config, PGVECTOR_REVISION)

    teacher_id, course_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as connection:
        schema = connection.execute(
            text("SELECT extnamespace::regnamespace::text FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one()
        assert schema == "extensions"
        connection.execute(
            text("INSERT INTO users (id, email, password_hash, name, role) VALUES (:id, :email, 'x', 'T', 'teacher')"),
            {"id": teacher_id, "email": f"teacher-{teacher_id}@example.test"},
        )
        connection.execute(
            text("INSERT INTO courses (id, teacher_id, title, status) VALUES (:id, :teacher_id, 'C', 'published')"),
            {"id": course_id, "teacher_id": teacher_id},
        )
        connection.execute(
            text(
                "INSERT INTO rag_documents (id, source_type, course_id, content, content_hash, model_version, embedding) "
                "VALUES (:id, 'course', :course_id, 'C', 'h', 'v', CAST(:embedding AS extensions.vector))"
            ),
            {"id": uuid.uuid4(), "course_id": course_id, "embedding": _vector(0)},
        )
        similarity = connection.execute(
            text(
                "SELECT 1 - (embedding OPERATOR(extensions.<=>) CAST(:query AS extensions.vector)) FROM rag_documents"
            ),
            {"query": _vector(0)},
        ).scalar_one()
        assert abs(similarity - 1.0) < 1e-6
        # 刪掉課程時向量跟著刪，草稿或刪除的課不會殘留在檢索資料裡
        connection.execute(text("DELETE FROM courses WHERE id = :id"), {"id": course_id})
        assert connection.execute(text("SELECT count(*) FROM rag_documents")).scalar_one() == 0

    indexes = {index["name"] for index in inspect(engine).get_indexes("rag_documents")}
    assert "ix_rag_documents_embedding" in indexes


def test_024_downgrade_then_upgrade_again(migration_database: tuple[Config, Engine]) -> None:
    config, engine = migration_database
    command.upgrade(config, PGVECTOR_REVISION)
    command.downgrade(config, UPSTREAM_REVISION)
    assert "rag_documents" not in inspect(engine).get_table_names()
    # 擴充功能留著，再升級一次也不會因為「已存在」而失敗
    command.upgrade(config, PGVECTOR_REVISION)
    assert "rag_documents" in inspect(engine).get_table_names()
