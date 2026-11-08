"""把已發布課程轉成向量，存進 pgvector（rag_documents）。課程改過、換了模型版本才會重算。

預設只試跑（dry-run），印出幾門要建索引；加上 --apply 和相符的 --confirm-database 才寫入。
草稿或下架的課程會移除向量，避免被找到。
檔名沿用舊版（舊版寫入 course_embeddings 的 JSONB 欄位），組員的操作方式不變。
"""

import argparse
import os

from sqlalchemy import delete, select
from sqlalchemy.engine import make_url

from backend.core.config import get_database_url
from backend.core.database import SessionLocal
from backend.models.rag_document import SOURCE_COURSE, RagDocument
from backend.models.student import Course
from backend.services.ai_semantic import course_hash, course_text, embed_texts

BATCH_SIZE = 4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-database", default="")
    args = parser.parse_args()
    version = os.environ.get("AI_COURSE_EMBEDDING_VERSION", "")
    if not version:
        parser.error("AI_COURSE_EMBEDDING_VERSION is required")
    target = make_url(get_database_url()).database
    if args.apply and (not target or args.confirm_database != target):
        parser.error("--confirm-database must match the target database name")
    with SessionLocal() as db:
        courses = db.scalars(
            select(Course).where(Course.status == "published").order_by(Course.id)
        ).all()
        published = {course.id for course in courses}
        existing = {
            row.course_id: row
            for row in db.scalars(
                select(RagDocument).where(
                    RagDocument.source_type == SOURCE_COURSE, RagDocument.chunk_index == 0
                )
            )
        }
        stale = [course_id for course_id in existing if course_id not in published]
        todo = [
            c
            for c in courses
            if c.id not in existing
            or existing[c.id].model_version != version
            or existing[c.id].content_hash != course_hash(c)
        ]
        if not args.apply:
            print(f"published={len(courses)} pending={len(todo)} unpublished_to_remove={len(stale)} mode=dry-run")
            return
        if stale:
            db.execute(delete(RagDocument).where(RagDocument.course_id.in_(stale)))
            db.commit()
        for start in range(0, len(todo), BATCH_SIZE):
            batch = todo[start : start + BATCH_SIZE]
            texts = [course_text(course) for course in batch]
            vectors = embed_texts(texts)
            if vectors is None:
                db.rollback()
                raise RuntimeError("embedding_gateway_unavailable")
            for course, text, vector in zip(batch, texts, vectors, strict=True):
                row = existing.get(course.id)
                if row is None:
                    row = RagDocument(source_type=SOURCE_COURSE, course_id=course.id, chunk_index=0)
                    db.add(row)
                row.title = (course.title or "")[:200]
                row.content = text
                row.model_version = version
                row.content_hash = course_hash(course)
                row.embedding = vector
            # 每批各自提交：中斷後重跑會從還沒完成的課程繼續
            db.commit()
            if (start + len(batch)) % 40 == 0 or start + len(batch) == len(todo):
                print(f"indexed={start + len(batch)}/{len(todo)}", flush=True)
        print(f"published={len(courses)} indexed={len(todo)} removed={len(stale)} mode=apply")


if __name__ == "__main__":
    main()
