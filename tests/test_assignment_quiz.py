"""題庫作業：老師上傳教材請 AI 出題（預覽、重新生成）、存成作業；學生作答、看錯題與解析。"""

import json
import uuid

import pytest

from backend.services import ai_quiz, llm
from tests.conftest import bind, issue_code, start_conversation

QUESTIONS = [
    {
        "type": "single",
        "difficulty": "easy",
        "topic": "五線譜與譜號",
        "question": "高音譜號的五條線，由下往上排列的音名為何？",
        "options": ["E、G、B、D、F", "F、A、C、E、G", "C、D、E、F、G", "G、B、D、F、A"],
        "answers": [0],
        "hint": "想想高音譜號的線間口訣。",
        "explanation": "線上的音由下往上是 E、G、B、D、F。",
    },
    {
        "type": "multiple",
        "difficulty": "medium",
        "topic": "拍號",
        "question": "下列哪些拍號每小節有三拍？",
        "options": ["3/4", "3/8", "4/4", "2/4"],
        "answers": [0, 1],
        "hint": "看上面的數字。",
        "explanation": "拍號上面的數字代表每小節的拍數。",
    },
    {
        "type": "truefalse",
        "difficulty": "easy",
        "topic": "音符時值",
        "question": "在 4/4 拍中，二分音符佔兩拍。",
        "options": ["正確", "錯誤"],
        "answers": [0],
        "hint": "二分音符是四分音符的幾倍？",
        "explanation": "二分音符的時值是四分音符的兩倍。",
    },
]


@pytest.fixture
def fake_llm(monkeypatch):
    """假的 AI：記下收到的內容，回傳固定題目（另外夾一題格式錯的，應該被剔掉）。"""
    seen = {}

    def reply(system_instruction, content, feature=None, temperature=0.3, timeout_seconds=None):
        seen["content"] = content
        seen["feature"] = feature
        broken = {"type": "single", "question": "壞掉的題目", "options": ["a", "b"], "answers": [5]}
        return "```json\n" + json.dumps({"questions": QUESTIONS + [broken]}, ensure_ascii=False) + "\n```", None

    monkeypatch.setattr(llm, "generate_text_with_reason", reply)
    return seen


@pytest.fixture
def setup(make_user, make_course, login):
    teacher = make_user("teacher", name="許雨天")
    student = make_user("student", name="林克")
    course = make_course(teacher)
    teacher_client = login(teacher)
    student_client = login(student)
    conversation_id = start_conversation(student_client, course)
    code = issue_code(teacher_client, conversation_id).json()["code"]
    assert bind(student_client, conversation_id, code).status_code == 200
    return teacher, student, course, teacher_client, student_client


def generate(client, **extra):
    """送出背景出題。測試裡背景工作會在回應後立刻跑完，所以接著讀那筆工作就是結果。"""
    data = {"count": "10", "types": "single,multiple,truefalse", "difficulty": "mixed"}
    data.update(extra)
    files = {"file": ("基礎樂理.txt", "五線譜與譜號：高音譜號……".encode("utf-8"), "text/plain")}
    return client.post("/teacher/quiz/jobs", data=data, files=files)


def job_of(client, response):
    assert response.status_code == 202, response.text
    return client.get(f"/teacher/quiz/jobs/{response.json()['id']}").json()


def create_quiz(teacher_client, course, student, questions=QUESTIONS):
    return teacher_client.post(
        "/teacher/assignments",
        data={
            "course_id": str(course.id),
            "student_id": str(student.id),
            "kind": "quiz",
            "title": "基礎樂理｜單元測驗",
            "questions": json.dumps(questions, ensure_ascii=False),
        },
    )


def test_老師上傳教材_背景出題完成後可以審查_剔除格式錯的題目(setup, fake_llm):
    _, _, _, teacher_client, _ = setup
    queued = generate(teacher_client, title="基礎樂理")
    assert queued.json()["status"] == "queued"
    job = job_of(teacher_client, queued)
    assert job["status"] == "succeeded", job
    assert job["title"] == "基礎樂理" and job["source_filename"] == "基礎樂理.txt"
    assert job["progress"] == 3
    assert [item["type"] for item in job["questions"]] == ["single", "multiple", "truefalse"]
    assert job["questions"][0]["hint"] == "想想高音譜號的線間口訣。"
    assert "五線譜與譜號" in fake_llm["content"]
    assert "single, multiple, truefalse" in fake_llm["content"]
    assert fake_llm["feature"] == llm.FEATURE_QUIZ_GENERATION
    # 列表只給狀態，不帶題目
    listed = teacher_client.get("/teacher/quiz/jobs").json()
    assert [item["id"] for item in listed] == [job["id"]] and listed[0]["questions"] is None


def test_出題設定不合理或檔案不支援會馬上擋下(setup, fake_llm):
    _, _, _, teacher_client, _ = setup
    assert generate(teacher_client, count="0").status_code == 400
    assert generate(teacher_client, count="31").status_code == 400
    assert generate(teacher_client, types="essay").status_code == 400
    assert generate(teacher_client, difficulty="extreme").status_code == 400
    docx = teacher_client.post("/teacher/quiz/jobs", files={"file": ("a.docx", b"PK", "application/zip")})
    assert docx.status_code == 400 and "PDF" in docx.json()["detail"]
    assert teacher_client.get("/teacher/quiz/jobs").json() == []


def test_AI沒有回應時工作標成失敗並說明原因(setup):
    _, _, _, teacher_client, _ = setup
    job = job_of(teacher_client, generate(teacher_client))
    assert job["status"] == "failed"
    assert "測試中不呼叫 LLM" in job["error"]


def test_本機模型分批出題_忙碌會等一下再試_不重複(setup, monkeypatch):
    """千問等本機模型：每批讀一段教材出 4 題，遇到閘道忙碌（503）等一下重試。"""
    _, _, _, teacher_client, _ = setup
    monkeypatch.setenv("QUIZ_GENERATION_LLM_PROVIDER", "local")
    monkeypatch.setattr(ai_quiz, "BUSY_WAIT_SECONDS", 0)
    monkeypatch.setattr(ai_quiz, "LOCAL_CHUNK_CHARS", 40)
    calls = []

    def reply(system_instruction, content, feature=None, temperature=0.3, timeout_seconds=None):
        calls.append(content)
        if len(calls) == 1:
            return None, "local（qwen3）：503 本機模型忙碌中或沒有開"
        batch = len(calls)
        questions = [
            {**QUESTIONS[2], "question": f"第 {batch} 批第 {index} 個敘述是對的。"} for index in range(4)
        ]
        # 每批都夾一題和前面重複的，應該被剔掉
        questions.append({**QUESTIONS[2], "question": "第 2 批第 0 個敘述是對的。"})
        return json.dumps({"questions": questions}, ensure_ascii=False), None

    monkeypatch.setattr(llm, "generate_text_with_reason", reply)
    long_text = "\n".join(f"第 {index} 段：音符時值與拍號的說明。" for index in range(12))
    response = teacher_client.post(
        "/teacher/quiz/jobs",
        data={"count": "10", "types": "truefalse", "difficulty": "easy"},
        files={"file": ("長教材.txt", long_text.encode("utf-8"), "text/plain")},
    )
    job = job_of(teacher_client, response)
    assert job["status"] == "succeeded", job
    assert job["provider"] == "local"
    assert len(job["questions"]) == 10
    assert len({item["question"] for item in job["questions"]}) == 10
    # 1 次忙碌 + 3 批（4、4、2 題）；後面的批次會附上已出過的題目
    assert len(calls) == 4
    assert "請根據以上教材出 2 題" in calls[-1] and "前面已經出過" in calls[-1]
    # 每批只送一段教材，不是整份
    assert all(len(content.split("---")[0]) < len(long_text) for content in calls)


def test_PDF教材可以讀出文字():
    import pymupdf

    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Treble clef lines: E G B D F")
    text = ai_quiz.extract_text("theory.pdf", document.tobytes())
    assert "Treble clef" in text


def scanned_pdf(text: str) -> bytes:
    """做一份沒有文字層的 PDF：先把字畫成圖片，再把圖片貼進新的 PDF。"""
    import pymupdf

    source = pymupdf.open()
    source.new_page().insert_text((72, 100), text, fontsize=28)
    image = source[0].get_pixmap(dpi=150).tobytes("png")
    scanned = pymupdf.open()
    page = scanned.new_page()
    page.insert_image(page.rect, stream=image)
    return scanned.tobytes()


def test_掃描的PDF頁面改用OCR_有文字的頁面不跑OCR(monkeypatch):
    import pymupdf

    document = pymupdf.open(stream=scanned_pdf("scan"), filetype="pdf")
    document.new_page().insert_text((72, 72), "Treble clef lines: E G B D F")
    ocr_calls = []
    monkeypatch.setattr(ai_quiz, "ocr_page", lambda page: ocr_calls.append(page.number) or "Bass clef lines: G B D F A")
    text = ai_quiz.extract_text("theory.pdf", document.tobytes())
    assert ocr_calls == [0]
    assert text.index("Bass clef") < text.index("Treble clef")  # 照頁碼順序


def test_OCR也讀不到字時_告訴老師原因(monkeypatch):
    monkeypatch.setattr(ai_quiz, "ocr_page", lambda page: "")
    with pytest.raises(ai_quiz.QuizGenerationError, match="讀不到文字"):
        ai_quiz.extract_text("scan.pdf", scanned_pdf("scan"))


def test_真的用Tesseract辨識掃描的PDF():
    import shutil

    if shutil.which("tesseract") is None:
        pytest.skip("這台電腦沒有裝 Tesseract（Docker 裡有）")
    text = ai_quiz.extract_text("scan.pdf", scanned_pdf("Treble clef lines E G B D F"))
    assert "Treble" in text


def test_學生和其他老師看不到出題紀錄(setup, make_user, login, fake_llm):
    _, _, _, teacher_client, student_client = setup
    assert generate(student_client).status_code in (401, 403)
    job = job_of(teacher_client, generate(teacher_client))
    other = login(make_user("teacher"))
    assert other.get(f"/teacher/quiz/jobs/{job['id']}").status_code == 404
    assert other.delete(f"/teacher/quiz/jobs/{job['id']}").status_code == 404
    assert other.get("/teacher/quiz/jobs").json() == []


def test_老師審查改答案後發成作業_留下AI原版與老師版本(setup, fake_llm, db):
    from backend.models.quiz_job import QuizGenerationJob

    _, student, course, teacher_client, student_client = setup
    job = job_of(teacher_client, generate(teacher_client))
    reviewed = [dict(item) for item in job["questions"][:2]]
    reviewed[0]["answers"] = [1]  # 老師覺得 AI 的答案錯了，改成 B
    response = teacher_client.post(
        "/teacher/assignments",
        data={
            "course_id": str(course.id),
            "student_id": str(student.id),
            "kind": "quiz",
            "title": "基礎樂理",
            "questions": json.dumps(reviewed, ensure_ascii=False),
            "quiz_job_id": job["id"],
        },
    )
    assert response.status_code == 201, response.text
    saved = db.get(QuizGenerationJob, uuid.UUID(job["id"]))
    db.refresh(saved)
    assert saved.status == "published" and str(saved.assignment_id) == response.json()["id"]
    assert saved.questions[0]["answers"] == [0] and saved.final_questions[0]["answers"] == [1]
    assert len(saved.final_questions) == 2
    # 發過就不再列出，也不能再發一次
    assert teacher_client.get("/teacher/quiz/jobs").json() == []
    again = teacher_client.post(
        "/teacher/assignments",
        data={
            "course_id": str(course.id),
            "student_id": str(student.id),
            "kind": "quiz",
            "title": "基礎樂理",
            "questions": json.dumps(reviewed, ensure_ascii=False),
            "quiz_job_id": job["id"],
        },
    )
    assert again.status_code == 400
    teacher_view = teacher_client.get(f"/teacher/assignments/{response.json()['id']}/quiz").json()
    assert teacher_view[0]["answers"] == [1]


def test_老師可以刪掉不要的出題(setup, fake_llm):
    _, _, _, teacher_client, _ = setup
    job = job_of(teacher_client, generate(teacher_client))
    assert teacher_client.delete(f"/teacher/quiz/jobs/{job['id']}").status_code == 204
    assert teacher_client.get("/teacher/quiz/jobs").json() == []


def test_太久沒動的出題中工作會標成中斷(setup, db, make_user):
    from datetime import datetime, timedelta, timezone

    from backend.models.quiz_job import QuizGenerationJob

    teacher, _, _, teacher_client, _ = setup
    job = QuizGenerationJob(
        teacher_id=teacher.id,
        status="running",
        settings={"count": 5, "types": ["single"], "difficulty": "easy"},
        source_filename="a.txt",
        source_text="教材",
        progress=2,
        updated_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db.add(job)
    db.commit()
    db.execute(
        QuizGenerationJob.__table__.update()
        .where(QuizGenerationJob.id == job.id)
        .values(updated_at=datetime.now(timezone.utc) - timedelta(hours=1))
    )
    listed = teacher_client.get("/teacher/quiz/jobs").json()
    assert listed[0]["status"] == "failed" and "中斷" in listed[0]["error"]


def test_存題庫作業_學生看不到答案_老師看得到(setup):
    _, student, course, teacher_client, student_client = setup
    created = create_quiz(teacher_client, course, student)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "quiz" and body["question_count"] == 3 and body["teacher_name"] == "許雨天"

    student_view = student_client.get(f"/api/student/assignments/{body['id']}/quiz").json()
    assert [item["position"] for item in student_view] == [1, 2, 3]
    assert "answers" not in student_view[0] and "explanation" not in student_view[0]
    assert student_view[0]["hint"] == "想想高音譜號的線間口訣。"
    assert student_view[2]["options"] == ["正確", "錯誤"]

    teacher_view = teacher_client.get(f"/teacher/assignments/{body['id']}/quiz").json()
    assert teacher_view[1]["answers"] == [0, 1]


def test_題庫作業一定要有題目_題目格式錯會說第幾題(setup):
    _, student, course, teacher_client, _ = setup
    assert create_quiz(teacher_client, course, student, questions=[]).status_code == 400
    bad = [QUESTIONS[0], {**QUESTIONS[1], "answers": [0]}]
    response = create_quiz(teacher_client, course, student, questions=bad)
    assert response.status_code == 400 and "第 2 題" in response.json()["detail"]


def test_學生作答_只回傳錯題與解析_可以重複練習(setup):
    _, student, course, teacher_client, student_client = setup
    assignment = create_quiz(teacher_client, course, student).json()
    questions = student_client.get(f"/api/student/assignments/{assignment['id']}/quiz").json()
    ids = [item["id"] for item in questions]
    url = f"/api/student/assignments/{assignment['id']}/quiz/attempts"

    # 第一次：第 1 題對，第 2 題多選只選一個（算錯），第 3 題錯
    first = student_client.post(
        url,
        json={"answers": [{"question_id": ids[0], "selected": [0]}, {"question_id": ids[1], "selected": [0]}, {"question_id": ids[2], "selected": [1]}]},
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["attempt_no"] == 1
    assert [item["position"] for item in body["wrong"]] == [2, 3]
    assert body["wrong"][0]["selected"] == [0] and body["wrong"][0]["answers"] == [0, 1]
    assert body["wrong"][1]["explanation"] == "二分音符的時值是四分音符的兩倍。"
    assert "correct_count" not in body

    second = student_client.post(
        url,
        json={"answers": [{"question_id": ids[0], "selected": [0]}, {"question_id": ids[1], "selected": [1, 0]}, {"question_id": ids[2], "selected": [1]}]},
    ).json()
    assert second["attempt_no"] == 2 and [item["position"] for item in second["wrong"]] == [3]

    history = student_client.get(url).json()
    assert [item["attempt_no"] for item in history] == [1, 2]
    assert [item["attempt_no"] for item in teacher_client.get(f"/teacher/assignments/{assignment['id']}/quiz/attempts").json()] == [1, 2]
    listed = student_client.get("/api/student/assignments").json()[0]
    assert listed["submission_count"] == 2


def test_作答要每題都答_單選不能選兩個(setup):
    _, student, course, teacher_client, student_client = setup
    assignment = create_quiz(teacher_client, course, student).json()
    ids = [item["id"] for item in student_client.get(f"/api/student/assignments/{assignment['id']}/quiz").json()]
    url = f"/api/student/assignments/{assignment['id']}/quiz/attempts"
    missing = student_client.post(url, json={"answers": [{"question_id": ids[0], "selected": [0]}]})
    assert missing.status_code == 400 and "第 2、3 題" in missing.json()["detail"]
    double = student_client.post(
        url,
        json={"answers": [{"question_id": ids[0], "selected": [0, 1]}, {"question_id": ids[1], "selected": [0, 1]}, {"question_id": ids[2], "selected": [0]}]},
    )
    assert double.status_code == 400 and "第 1 題" in double.json()["detail"]


def test_別人拿不到題目與作答(setup, make_user, login):
    _, student, course, teacher_client, _ = setup
    assignment = create_quiz(teacher_client, course, student).json()
    other_student = login(make_user("student"))
    other_teacher = login(make_user("teacher"))
    assert other_student.get(f"/api/student/assignments/{assignment['id']}/quiz").status_code == 404
    assert other_student.post(f"/api/student/assignments/{assignment['id']}/quiz/attempts", json={"answers": []}).status_code == 404
    assert other_teacher.get(f"/teacher/assignments/{assignment['id']}/quiz").status_code == 404


def test_重新生成用同一份教材再出一次_舊的不再列出(setup, fake_llm):
    _, _, _, teacher_client, _ = setup
    first = job_of(teacher_client, generate(teacher_client, title="基礎樂理"))
    response = teacher_client.post(f"/teacher/quiz/jobs/{first['id']}/retry")
    second = job_of(teacher_client, response)
    assert second["id"] != first["id"] and second["status"] == "succeeded"
    assert second["title"] == "基礎樂理" and second["settings"] == first["settings"]
    assert [item["id"] for item in teacher_client.get("/teacher/quiz/jobs").json()] == [second["id"]]
