from fastapi.testclient import TestClient

from backend.main import app
from backend.models.student import Course
from backend.models.teacher import TeacherDB


def set_profile(db, user, **fields):
    """老師帳號建立時可能已經有資料（申請核准時建立），有就改、沒有才新增。"""
    profile = db.query(TeacherDB).filter(TeacherDB.user_id == user.id).first()
    if profile is None:
        profile = TeacherDB(user_id=user.id, name=user.name, gender="未提供")
        db.add(profile)
    for key, value in fields.items():
        setattr(profile, key, value)


def featured(limit=12):
    response = TestClient(app).get("/api/teachers/featured", params={"limit": limit})
    assert response.status_code == 200, response.text
    return response.json()


def test_only_active_teachers_with_published_courses(db, make_user):
    published = make_user("teacher", "首頁已發布老師")
    draft_only = make_user("teacher", "首頁只有草稿老師")
    inactive = make_user("teacher", "首頁停用老師")
    inactive.is_active = False
    db.add_all([
        Course(teacher_id=published.id, title="首頁測試課", status="published"),
        Course(teacher_id=draft_only.id, title="首頁草稿課", status="draft"),
        Course(teacher_id=inactive.id, title="首頁停用課", status="published"),
    ])
    # 三位都有照片：有照片的排最前面，篩選如果漏掉，另外兩位會排在前面被看到
    set_profile(db, published, expertise="電影配樂、遊戲 BGM", short_intros="帶你認識配樂。", photo_path="a.jpg")
    set_profile(db, draft_only, photo_path="b.jpg")
    set_profile(db, inactive, photo_path="c.jpg")
    db.commit()

    result = featured()
    names = [teacher["name"] for teacher in result]

    assert names[0] == "首頁已發布老師"
    assert "首頁只有草稿老師" not in names and "首頁停用老師" not in names
    # 專長只放第一項
    assert result[0]["specialty"] == "電影配樂"
    assert result[0]["bio"] == "帶你認識配樂。"


def test_teachers_with_photos_come_first_and_limit_is_respected(db, make_user):
    with_photo = make_user("teacher", "首頁有照片老師")
    set_profile(db, with_photo, photo_path="teachers/photo.jpg")
    for index in range(3):
        other = make_user("teacher", f"首頁其他老師{index}")
        db.add(Course(teacher_id=other.id, title=f"首頁其他課{index}", status="published"))
    db.add(Course(teacher_id=with_photo.id, title="首頁有照片的課", status="published"))
    db.commit()

    result = featured(limit=2)

    assert len(result) == 2
    assert result[0]["name"] == "首頁有照片老師"
    assert result[0]["photo_url"] == f"/api/images/teachers/{with_photo.id}"
