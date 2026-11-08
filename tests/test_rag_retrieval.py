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
    db.add_all([online, unspecified, in_person])
    db.flush()
    ids = {online.id, unspecified.id, in_person.id}

    def matched(include):
        statement = _apply_required_filters(
            select(Course.id).where(Course.id.in_(ids)), {"delivery_mode": "online"}, include_unspecified_delivery=include
        )
        return set(db.scalars(statement))

    assert matched(True) == {online.id, unspecified.id}
    assert matched(False) == {online.id}
