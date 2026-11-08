import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.models.student import Course
from backend.services import course_chat


@pytest.fixture
def fake_model(monkeypatch):
    """記下交給模型的內容，回覆由測試指定。語意排序維持原順序，不連閘道。"""
    calls = []
    state = {"reply": "可以看看這門課。"}

    def generate(system_instruction, content, *args, **kwargs):
        calls.append({"system": system_instruction, "content": content, "feature": kwargs.get("feature")})
        return state["reply"], None

    monkeypatch.setattr(course_chat.llm, "generate_text_with_reason", generate)
    monkeypatch.setattr(course_chat, "rank_public_courses_with_status", lambda db, rows, query: (list(rows), "ready"))
    return calls, state


def add_course(db, teacher, title, **fields):
    course = Course(teacher_id=teacher.id, title=title, status=fields.pop("status", "published"), **fields)
    db.add(course)
    db.commit()
    return course


def ask(*texts):
    messages = []
    for index, text in enumerate(texts):
        messages.append({"role": "user" if index % 2 == 0 else "assistant", "content": text})
    return TestClient(app).post("/api/course-chat", json={"messages": messages})


def test_reply_attaches_cards_for_courses_it_names(db, make_user, fake_model):
    calls, state = fake_model
    teacher = make_user("teacher", "測試老師")
    course = add_course(db, teacher, "聊天測試流行鋼琴", style="流行", price_per_lesson=900)
    draft = add_course(db, teacher, "聊天測試草稿課", status="draft")
    state["reply"] = "推薦你「聊天測試流行鋼琴」，一堂 NT$ 500。"

    response = ask("我想學流行鋼琴")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reply"] == state["reply"]
    # 卡片的價格來自資料庫，不是模型寫的 500
    assert [(card["id"], card["price_per_lesson"]) for card in body["courses"]] == [(str(course.id), 900)]
    assert course.title in calls[0]["system"]
    assert draft.title not in calls[0]["system"]
    assert calls[0]["feature"] == course_chat.FEATURE_COURSE_CHAT


def test_whole_conversation_goes_to_model(db, make_user, fake_model):
    calls, _state = fake_model

    response = ask("我想學鋼琴", "你的程度如何？", "完全沒學過")

    assert response.status_code == 200, response.text
    assert "學生：我想學鋼琴\n顧問：你的程度如何？\n學生：完全沒學過" in calls[0]["content"]


def test_conditions_the_student_said_come_first(db, make_user, fake_model):
    calls, _state = fake_model
    teacher = make_user("teacher")
    cheap = add_course(db, teacher, "聊天測試台中便宜課", region="台中市西屯區", price_per_lesson=800, delivery_mode="online")
    add_course(db, teacher, "聊天測試台北課", region="台北市大安區", price_per_lesson=800, delivery_mode="online")

    ask("想找台中的課", "好的", "一堂 1000 元以內，線上")

    listed = calls[0]["system"].split("可以推薦的課程：")[1]
    # 資料庫裡可能還有別的台中課，台北的課就算有列出也要排在後面
    assert cheap.title in listed
    assert "聊天測試台北課" not in listed or listed.index(cheap.title) < listed.index("聊天測試台北課")


def test_same_title_needs_teacher_name_for_a_card(db, make_user, fake_model):
    _calls, state = fake_model
    first = make_user("teacher", "甲老師")
    second = make_user("teacher", "乙老師")
    add_course(db, first, "聊天測試同名課")
    picked = add_course(db, second, "聊天測試同名課")

    state["reply"] = "很多老師都有開聊天測試同名課。"
    assert ask("推薦一下").json()["courses"] == []

    state["reply"] = "推薦乙老師的聊天測試同名課。"
    assert [card["id"] for card in ask("推薦一下").json()["courses"]] == [str(picked.id)]


def test_model_failure_lists_found_courses_instead(db, make_user, monkeypatch):
    monkeypatch.setattr(course_chat.llm, "generate_text_with_reason", lambda *args, **kwargs: (None, "閘道沒開"))
    teacher = make_user("teacher")
    courses = [add_course(db, teacher, f"聊天備援課 {index}", style="流行", price_per_lesson=1500) for index in range(4)]
    rows = [(course, "老師", None) for course in courses]
    monkeypatch.setattr(course_chat, "_candidates", lambda db, criteria, query: rows)

    response = ask("流行鋼琴，一堂 1000 元以內")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reply"] == course_chat.FALLBACK_REPLY
    assert [card["id"] for card in body["courses"]] == [str(course.id) for course in courses[:3]]
    # 沒有 AI 也照樣核對預算
    assert body["courses"][0]["warnings"] == ["每堂 NT$ 1,500，超過你說的 NT$ 1,000"]


def test_last_message_must_be_from_student(db, fake_model):
    response = TestClient(app).post(
        "/api/course-chat",
        json={"messages": [{"role": "user", "content": "嗨"}, {"role": "assistant", "content": "你好"}]},
    )

    assert response.status_code == 422


def test_cards_warn_about_budget_region_and_wrong_price(db, make_user, fake_model, monkeypatch):
    _calls, state = fake_model
    teacher = make_user("teacher", "核對老師")
    pricey = add_course(
        db, teacher, "聊天核對貴的課", region="台北市大安區", price_per_lesson=1800, delivery_mode="in_person"
    )
    fine = add_course(db, teacher, "聊天核對剛好的課", region="台中市西屯區", price_per_lesson=900, delivery_mode="in_person")
    online = add_course(db, teacher, "聊天核對線上課", region="高雄市", price_per_lesson=800, delivery_mode="online")
    # 只看這三門，不受資料庫裡其他課影響
    rows = [(course, "核對老師", None) for course in (pricey, fine, online)]
    monkeypatch.setattr(course_chat, "_candidates", lambda db, criteria, query: rows)
    state["reply"] = (
        "「聊天核對貴的課」一堂 NT$800，很划算。\n\n"
        "「聊天核對剛好的課」每堂 900 元，在你的預算 1000 元以內。\n\n"
        "「聊天核對線上課」NT$ 800，線上就能上。"
    )

    cards = {card["id"]: card["warnings"] for card in ask("台中的課，一堂 1000 元以內").json()["courses"]}

    assert cards[str(pricey.id)] == [
        "每堂 NT$ 1,800，超過你說的 NT$ 1,000",
        "上課地點在台北市大安區，不是你說的台中市",
        "回覆寫的價格和課程資料不同，以這張卡片為準",
    ]
    assert cards[str(fine.id)] == []
    # 線上課不比地區
    assert cards[str(online.id)] == []


def test_course_delivery_mode_only_accepts_online_or_in_person(db, make_user):
    from sqlalchemy.exc import IntegrityError

    teacher = make_user("teacher")
    with pytest.raises(IntegrityError):
        add_course(db, teacher, "上課方式寫中文", delivery_mode="線上與實體")


def test_price_check_follows_teacher_for_same_title_and_longer_title_wins(db, make_user, fake_model, monkeypatch):
    _calls, state = fake_model
    first = make_user("teacher", "甲老師")
    second = make_user("teacher", "乙老師")
    cheap = add_course(db, first, "兒童古典鋼琴", price_per_lesson=1000)
    dear = add_course(db, second, "兒童古典鋼琴", price_per_lesson=1800)
    short = add_course(db, second, "古典鋼琴", price_per_lesson=1500)
    rows = [(cheap, "甲老師", None), (dear, "乙老師", None), (short, "乙老師", None)]
    monkeypatch.setattr(course_chat, "_candidates", lambda db, criteria, query: rows)
    state["reply"] = "1. 兒童古典鋼琴（甲老師）NT$1000。\n2. 兒童古典鋼琴（乙老師）NT$1800。"

    cards = {card["id"]: card["warnings"] for card in ask("小孩想學古典").json()["courses"]}

    # 「兒童古典鋼琴」裡的「古典鋼琴」不是另一門課；兩門同名課各自的價格都寫對
    assert cards == {str(cheap.id): [], str(dear.id): []}

    state["reply"] = "兒童古典鋼琴（乙老師）一堂 NT$1000。"
    assert ask("小孩想學古典").json()["courses"][0]["warnings"] == ["回覆寫的價格和課程資料不同，以這張卡片為準"]
