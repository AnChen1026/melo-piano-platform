"""老師管理課程與參考 MIDI（SRS CAT-02、PRA-01、FILE-01）。"""

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import func, select

from backend.models.student import ReferenceMidi
from backend.services import course as course_service
from tests.conftest import FULL_TEACHER_PROFILE, bind, issue_code, start_conversation

SAMPLE_MIDI = Path(__file__).resolve().parents[1] / "backend" / "audio_scoring" / "midi_test_data" / "test1.mid"
SAMPLE_MIDI_2 = Path(__file__).resolve().parents[1] / "backend" / "audio_scoring" / "midi_test_data" / "test2.mid"


def upload_midi(client, course_id, content: bytes, filename: str = "song.mid"):
    return client.post(
        f"/courses/{course_id}/reference-midi",
        files={"midi": (filename, content, "audio/midi")},
    )


def test_老師可以修改草稿並發布(make_user, make_course, login):
    teacher = make_user("teacher")
    course = make_course(teacher, status="draft")
    client = login(teacher)

    response = client.patch(
        f"/courses/{course.id}",
        json={"title": "古典入門", "level": "入門", "delivery_mode": "hybrid", "price_per_lesson": 1200},
    )
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "古典入門"
    assert response.json()["delivery_mode"] == "hybrid"
    assert response.json()["status"] == "draft"
    assert str(course.id) not in {row["id"] for row in client.get("/api/courses").json()}

    assert client.patch(f"/courses/{course.id}", json={"status": "published"}).status_code == 200
    assert str(course.id) in {row["id"] for row in client.get("/api/courses").json()}


def test_課程欄位要符合規格(make_user, make_course, login):
    teacher = make_user("teacher")
    course = make_course(teacher)
    client = login(teacher)

    for body in (
        {"level": "大師"},
        {"delivery_mode": "到府"},
        {"price_per_lesson": -1},
        {"status": "paused"},
        {"title": "   "},
    ):
        assert client.patch(f"/courses/{course.id}", json=body).status_code == 400, body
    assert client.post("/teacher/profile", json=FULL_TEACHER_PROFILE).status_code == 200
    assert client.post("/courses", json={"title": "新課", "level": "大師"}).status_code == 400


def test_不能修改別人的課程或上傳別人的MIDI(make_user, make_course, login):
    owner = make_user("teacher")
    course = make_course(owner)
    stranger = login(make_user("teacher"))

    assert stranger.patch(f"/courses/{course.id}", json={"title": "改掉"}).status_code == 403
    assert upload_midi(stranger, course.id, SAMPLE_MIDI.read_bytes()).status_code == 403
    assert stranger.delete(f"/courses/{course.id}").status_code == 403


def test_參考MIDI只收真的MIDI並同步metadata(db, make_user, make_course, login):
    teacher = make_user("teacher")
    course = make_course(teacher)
    client = login(teacher)

    assert upload_midi(client, course.id, b"not a midi file").status_code == 400
    assert upload_midi(client, course.id, SAMPLE_MIDI.read_bytes(), "song.txt").status_code == 400
    assert upload_midi(client, course.id, b"").status_code == 400
    assert db.scalar(
        select(func.count()).select_from(ReferenceMidi).where(ReferenceMidi.course_id == course.id)
    ) == 0

    midi_bytes = SAMPLE_MIDI.read_bytes()
    response = upload_midi(client, course.id, midi_bytes)
    assert response.status_code == 200, response.text
    assert response.json()["has_reference_midi"] is True
    assert "reference_midi_path" not in response.json()
    db.expire_all()
    reference = db.scalar(select(ReferenceMidi).where(ReferenceMidi.course_id == course.id))
    assert reference is not None
    assert reference.teacher_id == teacher.id
    assert reference.storage_key == db.get(type(course), course.id).reference_midi_path
    assert reference.original_filename == "song.mid"
    assert reference.content_sha256 == hashlib.sha256(midi_bytes).hexdigest()
    assert reference.file_size_bytes == len(midi_bytes)
    assert client.get(f"/courses/{course.id}/reference-midi").content == midi_bytes

    replacement_bytes = SAMPLE_MIDI_2.read_bytes()
    original_reference_id = reference.id
    replacement = upload_midi(client, course.id, replacement_bytes, "replacement.midi")
    assert replacement.status_code == 200, replacement.text
    db.expire_all()
    replaced_reference = db.scalar(select(ReferenceMidi).where(ReferenceMidi.course_id == course.id))
    assert db.scalar(
        select(func.count()).select_from(ReferenceMidi).where(ReferenceMidi.course_id == course.id)
    ) == 1
    assert replaced_reference is not None
    assert replaced_reference.id == original_reference_id
    assert replaced_reference.original_filename == "replacement.midi"
    assert replaced_reference.content_sha256 == hashlib.sha256(replacement_bytes).hexdigest()
    assert replaced_reference.file_size_bytes == len(replacement_bytes)
    assert client.get(f"/courses/{course.id}/reference-midi").content == replacement_bytes


def test_參考MIDI資料庫提交失敗會清掉新檔案(db, make_user, make_course, monkeypatch, tmp_path):
    teacher = make_user("teacher")
    course = make_course(teacher)
    monkeypatch.setattr(course_service, "MIDI_UPLOAD_DIR", tmp_path / "uploads" / "midi")

    def fail_commit():
        raise RuntimeError("forced commit failure")

    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="forced commit failure"):
        course_service.save_reference_midi(
            db,
            teacher.id,
            course.id,
            "song.mid",
            SAMPLE_MIDI.read_bytes(),
        )

    assert list((tmp_path / "uploads" / "midi").rglob("*.mid")) == []


def test_參考MIDI只有綁定學生能下載(make_user, make_course, login):
    teacher = make_user("teacher")
    course = make_course(teacher)
    teacher_client = login(teacher)
    upload_midi(teacher_client, course.id, SAMPLE_MIDI.read_bytes())

    student_client = login(make_user("student"))
    conversation_id = start_conversation(student_client, course)
    assert student_client.get(f"/api/student/courses/{course.id}/reference-midi").status_code == 403

    code = issue_code(teacher_client, conversation_id).json()["code"]
    bind(student_client, conversation_id, code)
    response = student_client.get(f"/api/student/courses/{course.id}/reference-midi")
    assert response.status_code == 200
    assert response.content == SAMPLE_MIDI.read_bytes()


@pytest.mark.parametrize("failure_point", ["query", "commit"])
def test_metadata寫入失敗會清掉新檔且保留舊MIDI(db, make_user, make_course, monkeypatch, tmp_path, failure_point):
    teacher = make_user("teacher")
    course = make_course(teacher)
    midi_dir = tmp_path / "uploads" / "midi"
    monkeypatch.setattr(course_service, "MIDI_UPLOAD_DIR", midi_dir)
    course_service.save_reference_midi(db, teacher.id, course.id, "original.mid", SAMPLE_MIDI.read_bytes())
    old_path = course.reference_midi_path
    old_files = set(midi_dir.rglob("*.mid"))
    teacher_id, course_id = teacher.id, course.id

    def fail_query(*args, **kwargs):
        raise RuntimeError("forced metadata query failure")

    with monkeypatch.context() as patch:
        patch.setattr(db, failure_point, fail_query)
        with pytest.raises(RuntimeError, match="forced metadata query failure"):
            course_service.save_reference_midi(
                db, teacher_id, course_id, "replacement.mid", SAMPLE_MIDI_2.read_bytes()
            )

    assert set(midi_dir.rglob("*.mid")) == old_files
    db.expire_all()
    assert db.get(type(course), course_id).reference_midi_path == old_path
    reference = db.scalar(select(ReferenceMidi).where(ReferenceMidi.course_id == course_id))
    assert reference.storage_key == old_path
    assert reference.original_filename == "original.mid"
