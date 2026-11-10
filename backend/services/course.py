"""老師管理自己的課程：欄位檢查、修改與參考 MIDI。"""

import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import status
from sqlalchemy.orm import Session

from backend.core.uploads import MIDI_UPLOAD_DIR
from backend.core.storage import save_file, cleanup_files
from backend.models.student import Course, ReferenceMidi
from backend.services.student import StudentBusinessError

COURSE_LEVELS = ("入門", "初階", "中階", "進階", "不確定")
# hybrid：線上或實體皆可；空值只代表老師沒填
DELIVERY_MODES = ("online", "in_person", "hybrid")
COURSE_STATUSES = ("draft", "published", "archived")
MAX_MIDI_BYTES = 2 * 1024 * 1024
MIDI_SUFFIXES = (".mid", ".midi")


def check_course_fields(fields: dict) -> dict:
    """檢查並整理課程欄位。只處理有傳進來的欄位，空字串視為清空。"""
    cleaned = {}
    for name, value in fields.items():
        if isinstance(value, str):
            value = value.strip() or None
        cleaned[name] = value

    if "title" in cleaned:
        title = cleaned["title"]
        if not title:
            raise StudentBusinessError(status.HTTP_400_BAD_REQUEST, "課程名稱不能是空白。")
        if len(title) > 200:
            raise StudentBusinessError(status.HTTP_400_BAD_REQUEST, "課程名稱最多 200 字。")
    if cleaned.get("level") is not None and cleaned["level"] not in COURSE_LEVELS:
        raise StudentBusinessError(status.HTTP_400_BAD_REQUEST, "找課程度只能是入門、初階、中階、進階或不確定。")
    if cleaned.get("delivery_mode") is not None and cleaned["delivery_mode"] not in DELIVERY_MODES:
        raise StudentBusinessError(status.HTTP_400_BAD_REQUEST, "上課方式只能是線上、實體或線上實體皆可。")
    if cleaned.get("price_per_lesson") is not None and cleaned["price_per_lesson"] < 0:
        raise StudentBusinessError(status.HTTP_400_BAD_REQUEST, "單堂價格不能是負數。")
    if "status" in cleaned and cleaned["status"] not in COURSE_STATUSES:
        raise StudentBusinessError(status.HTTP_400_BAD_REQUEST, "課程狀態只能是草稿、已發布或已封存。")
    for name, limit in (("style", 100), ("region", 100), ("time_slots", 200), ("description", 2000)):
        if cleaned.get(name) is not None and len(cleaned[name]) > limit:
            raise StudentBusinessError(status.HTTP_400_BAD_REQUEST, f"欄位太長，最多 {limit} 字。")
    return cleaned


def get_own_course(db: Session, teacher_user_id: uuid.UUID, course_id: uuid.UUID) -> Course:
    course = db.get(Course, course_id)
    if course is None:
        raise StudentBusinessError(status.HTTP_404_NOT_FOUND, "找不到課程。")
    if course.teacher_id != teacher_user_id:
        raise StudentBusinessError(status.HTTP_403_FORBIDDEN, "不能管理其他教師的課程。")
    return course


def create_course(db: Session, teacher_user_id: uuid.UUID, fields: dict) -> Course:
    cleaned = check_course_fields({"status": "draft", **fields})
    if "title" not in cleaned:
        raise StudentBusinessError(status.HTTP_400_BAD_REQUEST, "課程名稱不能是空白。")
    course = Course(teacher_id=teacher_user_id, **cleaned)
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


def update_course(db: Session, teacher_user_id: uuid.UUID, course_id: uuid.UUID, fields: dict) -> Course:
    course = get_own_course(db, teacher_user_id, course_id)
    for name, value in check_course_fields(fields).items():
        setattr(course, name, value)
    db.commit()
    db.refresh(course)
    return course


def save_reference_midi(
    db: Session,
    teacher_user_id: uuid.UUID,
    course_id: uuid.UUID,
    filename: str,
    content: bytes,
) -> Course:
    """每門課一份參考 MIDI。換新檔時舊檔留著，已評分的練習仍能對回當時的曲子。"""
    course = get_own_course(db, teacher_user_id, course_id)
    if not filename.lower().endswith(MIDI_SUFFIXES):
        raise StudentBusinessError(status.HTTP_400_BAD_REQUEST, "請上傳 .mid 或 .midi 檔。")
    if len(content) == 0:
        raise StudentBusinessError(status.HTTP_400_BAD_REQUEST, "參考 MIDI 檔是空的。")
    if len(content) > MAX_MIDI_BYTES:
        raise StudentBusinessError(status.HTTP_400_BAD_REQUEST, "參考 MIDI 最大 2 MB。")
    if not content.startswith(b"MThd"):
        raise StudentBusinessError(status.HTTP_400_BAD_REQUEST, "這不是有效的 MIDI 檔。")

    folder = MIDI_UPLOAD_DIR / str(teacher_user_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4()}.mid"
    storage_key = save_file(path, content, "audio/midi")

    try:
        original_filename = filename.replace("\\", "/").rsplit("/", 1)[-1][-255:] or "reference.mid"
        course.reference_midi_path = storage_key
        reference = db.query(ReferenceMidi).filter(ReferenceMidi.course_id == course.id).one_or_none()
        if reference is None:
            reference = ReferenceMidi(course_id=course.id, teacher_id=teacher_user_id)
            db.add(reference)
        reference.teacher_id = teacher_user_id
        reference.storage_key = storage_key
        reference.original_filename = original_filename
        reference.content_sha256 = hashlib.sha256(content).hexdigest()
        reference.file_size_bytes = len(content)
        reference.updated_at = datetime.now(timezone.utc)

        db.commit()
    except Exception:
        db.rollback()
        cleanup_files([storage_key])
        raise
    db.refresh(course)
    return course


def save_course_image(db: Session, teacher_user_id: uuid.UUID, course_id: uuid.UUID, content: bytes) -> Course:
    from backend.services.images import save_image

    course = get_own_course(db, teacher_user_id, course_id)
    storage_key = save_image(content, "courses")
    course.image_path = storage_key
    try:
        db.commit()
    except Exception:
        db.rollback()
        cleanup_files([storage_key])
        raise
    db.refresh(course)
    return course
