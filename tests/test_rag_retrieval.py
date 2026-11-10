"""AI 找課檢索：查詢改寫與門檻的規則。數字依據見 docs/ai-course-finder/retrieval/report.md。"""

import pytest

from backend.services.rag_retrieval import MIN_SIMILARITY, build_query, should_gate


def test_build_query_strategies():
    turns = ["我想學爵士", "那有沒有進階一點的？"]
    assert build_query(turns, "last") == "那有沒有進階一點的？"
    assert build_query(turns, "recent") == "我想學爵士\n那有沒有進階一點的？"
    assert build_query(turns, "follow_up") == "我想學爵士\n那有沒有進階一點的？"
    # 第二句不是追問，只看最後一句
    assert build_query(["我想學爵士", "我其實比較想把古典奏鳴曲的結構弄懂"], "follow_up") == "我其實比較想把古典奏鳴曲的結構弄懂"


def test_recent_keeps_only_last_three_turns_and_skips_blank():
    assert build_query(["一", " ", "二", "三", "四"], "recent") == "二\n三\n四"
    assert build_query([], "recent") == ""
    with pytest.raises(ValueError):
        build_query(["x"], "unknown")


def test_gate_only_when_index_ready_no_criteria_and_low_score():
    low = MIN_SIMILARITY - 0.01
    assert should_gate("ready", {}, low)
    assert not should_gate("ready", {}, MIN_SIMILARITY)
    # 說了條件：照條件篩出的課就是答案，相似度低也不擋
    assert not should_gate("ready", {"region": "台中市", "level": None}, low)
    # 向量不完整或閘道沒開：沒有可靠的分數，不擋
    assert not should_gate("partial", {}, low)
    assert not should_gate("unavailable", {}, None)
    # 條件欄位都是 None 等於沒說
    assert should_gate("ready", {"level": None, "style": None}, low)


def test_delivery_filter_keeps_courses_without_delivery_mode(db, make_user):
    from sqlalchemy import select

    from backend.models.student import Course
    from backend.services.recommendation import _apply_required_filters

    teacher = make_user("teacher")
    online = Course(teacher_id=teacher.id, title="線上", status="published", delivery_mode="online")
    unspecified = Course(teacher_id=teacher.id, title="未填", status="published", delivery_mode=None)
    in_person = Course(teacher_id=teacher.id, title="實體", status="published", delivery_mode="in_person")
    hybrid = Course(teacher_id=teacher.id, title="皆可", status="published", delivery_mode="hybrid")
    db.add_all([online, unspecified, in_person, hybrid])
    db.flush()
    ids = {online.id, unspecified.id, in_person.id, hybrid.id}

    def matched(include):
        statement = _apply_required_filters(
            select(Course.id).where(Course.id.in_(ids)), {"delivery_mode": "online"}, include_unspecified_delivery=include
        )
        return set(db.scalars(statement))

    # 線上實體皆可的課一定符合；老師沒填的課預設也不排除
    assert matched(True) == {online.id, unspecified.id, hybrid.id}
    assert matched(False) == {online.id, hybrid.id}


def test_mentioned_teachers_matches_name_with_or_without_suffix():
    from backend.services.rag_retrieval import mentioned_teachers

    names = {"劉欣儀老師", "王小明", "乙"}
    assert mentioned_teachers(names, ["劉欣儀老師"]) == {"劉欣儀老師"}
    assert mentioned_teachers(names, ["想上劉欣儀的課"]) == {"劉欣儀老師"}
    assert mentioned_teachers(names, ["王 小明老師有教爵士嗎"]) == {"王小明"}
    # 一個字的名字太容易誤判，不比
    assert mentioned_teachers(names, ["乙級檢定"]) == set()
    # 只看最近三句：很早以前提過的老師不再算
    assert mentioned_teachers(names, ["劉欣儀老師", "好", "那流行的呢", "預算一千"]) == set()


def test_named_teacher_courses_come_first_and_are_not_gated(db, make_user, monkeypatch):
    from sqlalchemy import select

    from backend.models.student import Course
    from backend.services import ai_semantic, rag_retrieval

    named = make_user("teacher", "點名測試老師")
    other = make_user("teacher", "其他測試老師")
    theirs = Course(teacher_id=named.id, title="認識升降記號", status="published")
    unrelated = Course(teacher_id=other.id, title="爵士即興", status="published")
    db.add_all([theirs, unrelated])
    db.flush()

    # 索引沒有老師名字，「點名測試老師」和每門課都不像，分數全部低於門檻
    def low_scores(db, vector, version=None):
        return {course_id: 0.3 for course_id in db.scalars(select(Course.id).where(Course.status == "published"))}

    monkeypatch.setenv("AI_COURSE_EMBEDDING_VERSION", "test")
    monkeypatch.setattr(ai_semantic, "embed_texts", lambda texts: [[0.0]])
    monkeypatch.setattr(rag_retrieval, "published_course_scores", low_scores)

    without_name = rag_retrieval.retrieve_courses(db, ["隨便聊聊"], {})
    assert without_name.gated and without_name.rows == []

    result = rag_retrieval.retrieve_courses(db, ["點名測試老師"], {})
    assert not result.gated
    assert result.rows[0][0].id == theirs.id
