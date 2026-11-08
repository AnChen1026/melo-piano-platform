"""Search only reorders existing authorized candidates with current embeddings."""

from backend.models.rag_document import EMBEDDING_DIMENSION, SOURCE_COURSE, RagDocument
from backend.models.student import Course
from backend.services.ai_semantic import course_hash, rank_public_courses


def axis(index):
    """1024 維的單位向量，只有第 index 維是 1；兩個不同軸的餘弦相似度是 0。"""
    vector = [0.0] * EMBEDDING_DIMENSION
    vector[index] = 1.0
    return vector


def test_semantic_search_orders_current_embeddings_without_dropping_unindexed(
    db, make_user, monkeypatch
):
    teacher = make_user("teacher")
    first = Course(
        teacher_id=teacher.id, title="基礎", status="published", description="基本練習"
    )
    second = Course(
        teacher_id=teacher.id,
        title="配樂",
        status="published",
        description="影視主題曲",
    )
    third = Course(teacher_id=teacher.id, title="其他", status="published")
    db.add_all([first, second, third])
    db.flush()
    for course, vector in [(first, axis(1)), (second, axis(0))]:
        db.add(
            RagDocument(
                source_type=SOURCE_COURSE,
                course_id=course.id,
                content=course.title,
                model_version="test-v1",
                content_hash=course_hash(course),
                embedding=vector,
            )
        )
    db.commit()
    monkeypatch.setenv("AI_COURSE_EMBEDDING_VERSION", "test-v1")
    monkeypatch.setattr(
        "backend.services.ai_semantic.embed_texts", lambda texts: [axis(0)]
    )
    rows = [(first, "老師", None), (second, "老師", None), (third, "老師", None)]
    result = rank_public_courses(db, rows, "電影配樂")
    assert [r[0].id for r in result] == [second.id, first.id, third.id]
    second.description = "已修改的課程"
    assert [r[0].id for r in rank_public_courses(db, rows, "電影配樂")] == [
        first.id,
        second.id,
        third.id,
    ]


def test_recommendation_does_not_offer_drafts_or_over_budget_courses(
    db, make_user, monkeypatch
):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.services import ai_model_planner, ai_semantic

    teacher = make_user("teacher")
    valid = Course(
        teacher_id=teacher.id, title="可選", status="published", price_per_lesson=900
    )
    draft = Course(
        teacher_id=teacher.id, title="草稿", status="draft", price_per_lesson=900
    )
    expensive = Course(
        teacher_id=teacher.id, title="太貴", status="published", price_per_lesson=2000
    )
    db.add_all([valid, draft, expensive])
    db.commit()

    def plan(message, previous, previous_question=None):
        return {**previous, "_semantic_query": "電影配樂"}, ""

    monkeypatch.setattr(ai_model_planner, "plan_turn", plan)
    seen = []

    def rank(db, rows, query):
        seen.extend(row[0].id for row in rows)
        return list(reversed(rows)), "ready"

    monkeypatch.setattr(ai_semantic, "rank_public_courses_with_status", rank)
    response = TestClient(app).post(
        "/api/recommendations", json={"message": "想彈電影配樂，1200元以下"}
    )
    assert response.status_code == 200
    assert valid.id in seen
    assert draft.id not in seen and expensive.id not in seen
    result_ids = [item["course"]["id"] for item in response.json()["results"]]
    assert str(draft.id) not in result_ids and str(expensive.id) not in result_ids


def test_語意搜尋不可用時明確顯示一般排序(db, make_user, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.services import ai_model_planner, ai_semantic

    db.add(Course(teacher_id=make_user('teacher').id, title='課程', status='published')); db.commit()
    monkeypatch.setattr(ai_model_planner, 'plan_turn', lambda message, previous, previous_question=None: ({**previous, '_semantic_query': '電影配樂'}, ''))
    monkeypatch.setattr(ai_semantic, 'rank_public_courses_with_status', lambda db, rows, query: (rows, 'unavailable'))
    result = TestClient(app).post('/api/recommendations', json={'message': '電影配樂'}).json()
    assert result['status'] == 'done'
    assert '語意' in result['message'] and '一般' in result['message']


def test_pgvector_similarity_matches_cosine_and_ignores_other_model_versions(db, make_user):
    from backend.services.ai_semantic import course_similarities

    teacher = make_user("teacher")
    course = Course(teacher_id=teacher.id, title="爵士", status="published")
    other = Course(teacher_id=teacher.id, title="古典", status="published")
    db.add_all([course, other])
    db.flush()
    half = [0.0] * EMBEDDING_DIMENSION
    half[0] = half[1] = 1.0  # 和 axis(0) 夾 45 度，餘弦相似度 = 0.7071
    db.add_all(
        [
            RagDocument(source_type=SOURCE_COURSE, course_id=course.id, content="爵士", model_version="v1", content_hash="h", embedding=half),
            RagDocument(source_type=SOURCE_COURSE, course_id=other.id, content="古典", model_version="old", content_hash="h", embedding=axis(0)),
        ]
    )
    db.flush()
    found = course_similarities(db, [course.id, other.id], axis(0), "v1")
    assert set(found) == {course.id}
    assert abs(found[course.id][1] - 0.5**0.5) < 1e-6


def test_rag_document_rejects_course_rows_without_course(db):
    import pytest
    from sqlalchemy.exc import IntegrityError

    db.add(RagDocument(source_type=SOURCE_COURSE, content="x", model_version="v1", content_hash="h", embedding=axis(0)))
    with pytest.raises(IntegrityError):
        db.flush()
