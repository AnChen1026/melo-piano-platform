"""首頁對話找課規則。

這裡只整理訪客明確說出的條件，並從正式的已發布課程中查詢。
推薦理由也由實際欄位組成，不交給語言模型猜測。
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.models.student import Course, RecommendationItem, RecommendationSession
from backend.models.teacher import TeacherDB
from backend.models.user import User


CRITERIA_FIELDS = ("level", "style", "delivery_mode", "region", "max_price", "time_slot")
FIELD_LABELS = {
    "level": "程度",
    "style": "曲風",
    "delivery_mode": "上課方式",
    "region": "地區",
    "max_price": "預算",
    "time_slot": "時段",
}
QUESTIONS = {
    "level": "你目前的鋼琴程度如何？例如完全沒學過、初階、中階或進階。",
    "delivery_mode": "你偏好線上還是實體上課？不確定也可以直接說。",
}
UNKNOWN_ANSWERS = ("不確定", "不知道", "都可以", "沒差", "皆可", "無所謂")
UNSUPPORTED_INSTRUMENTS = ("吉他", "小提琴", "大提琴", "爵士鼓", "打鼓", "長笛", "薩克斯風", "烏克麗麗")


class RecommendationNotFound(Exception):
    """對談不存在、過期或不屬於目前瀏覽器。"""


class RecommendationConflict(Exception):
    """A different request is updating this conversation."""


def empty_criteria() -> dict[str, object | None]:
    return {field: None for field in CRITERIA_FIELDS}


def _contains_unknown(text: str) -> bool:
    return any(word in text for word in UNKNOWN_ANSWERS)


def _affirmed(text: str, phrase: str) -> bool:
    """避免把「不想古典」「不是初階」當成肯定條件。"""
    return phrase in text and not any(prefix + phrase in text for prefix in ("不", "不是", "不要", "不想"))


def parse_criteria(text: str) -> dict[str, object]:
    """保守解析明確文字；沒有把握的欄位不填。"""
    values: dict[str, object] = {}
    normalized = text.strip().lower()
    uncertain = _contains_unknown(normalized)

    level_aliases = (
        ("入門", ("完全沒學過", "零基礎", "沒學過", "初學", "新手", "入門")),
        ("初階", ("初階", "初級")),
        ("中階", ("中階", "中級")),
        ("進階", ("進階", "高階", "高級")),
    )
    for value, aliases in level_aliases:
        if not uncertain and any(_affirmed(normalized, alias) for alias in aliases):
            values["level"] = value
            break

    styles = sorted(
        (style for style in ("古典", "流行", "爵士", "即興", "兒童") if _affirmed(normalized, style)),
        key=normalized.find,
    )
    for style in styles:
        if style:
            values["style"] = style
            break

    has_online = _affirmed(normalized, "線上") or _affirmed(normalized, "遠距")
    has_in_person = _affirmed(normalized, "實體") or _affirmed(normalized, "面授")
    if has_online and not has_in_person:
        values["delivery_mode"] = "online"
    elif has_in_person and not has_online:
        values["delivery_mode"] = "in_person"

    region_match = re.search(
        r"((?:台|臺)北市|新北市|桃園市|台中市|臺中市|台南市|臺南市|高雄市|基隆市|新竹市|新竹縣|嘉義市|嘉義縣|彰化縣|苗栗縣|南投縣|雲林縣|屏東縣|宜蘭縣|花蓮縣|台東縣|臺東縣)([\u4e00-\u9fff]{1,4}(?:區|鄉|鎮|市))?",
        text,
    )
    if region_match:
        values["region"] = region_match.group(0).replace("臺", "台")

    price_match = re.search(r"(?:預算|每堂|一堂|最多)?\s*(\d{3,5})\s*元?\s*(?:以下|以內|內|最多|上限)", text)
    if not price_match:
        price_match = re.search(r"(?:預算|最多|上限)\D{0,5}(\d{3,5})", text)
    if price_match:
        values["max_price"] = int(price_match.group(1))

    for slot in ("平日上午", "平日下午", "平日晚上", "週末上午", "週末下午", "週末晚上", "平日", "週末"):
        if slot in normalized:
            values["time_slot"] = slot
            break
    return values


def _unsupported(text: str) -> bool:
    return any(instrument in text for instrument in UNSUPPORTED_INSTRUMENTS) and "鋼琴" not in text


def _load_owned(db: Session, session_id: uuid.UUID, owner_hash: str, lock: bool = False) -> RecommendationSession:
    statement = select(RecommendationSession).where(
            RecommendationSession.id == session_id,
            RecommendationSession.owner_hash == owner_hash,
            RecommendationSession.expires_at > datetime.now(timezone.utc),
        )
    if lock:
        statement = statement.with_for_update(nowait=True)
    try:
        row = db.scalar(statement)
    except OperationalError as exc:
        if getattr(exc.orig, "sqlstate", None) == "55P03":
            db.rollback()
            raise RecommendationConflict from None
        raise
    if row is None:
        raise RecommendationNotFound
    return row


def _append_message(row: RecommendationSession, role: str, content: str) -> None:
    row.messages = [*row.messages, {"role": role, "content": content}]


def _ask(row: RecommendationSession, field: str, question: str | None = None) -> None:
    question = question or QUESTIONS[field]
    row.asked_fields = [*row.asked_fields, field]
    row.question_count += 1
    row.status = "asking"
    row.question = question
    row.result_message = question
    _append_message(row, "assistant", question)


def _apply_required_filters(statement, criteria, include_unspecified_delivery=True):
    if criteria.get("level"):
        statement = statement.where(Course.level == criteria["level"])
    if criteria.get("style"):
        statement = statement.where(Course.style.is_not(None), Course.style.ilike(f"%{criteria['style']}%"))
    if criteria.get("delivery_mode"):
        # 線上實體皆可（hybrid）的課，學生要線上或實體都符合。
        # 老師沒填上課方式的課（空值）預設也不排除，卡片上再提醒向老師確認
        matches = Course.delivery_mode.in_([criteria["delivery_mode"], "hybrid"])
        statement = statement.where(
            or_(matches, Course.delivery_mode.is_(None)) if include_unspecified_delivery else matches
        )
    if criteria.get("region"):
        region = str(criteria["region"])
        statement = statement.where(Course.region.is_not(None), Course.region.ilike(f"%{region}%"))
    if criteria.get("max_price") is not None:
        statement = statement.where(
            Course.price_per_lesson.is_not(None), Course.price_per_lesson <= int(criteria["max_price"])
        )
    if criteria.get("time_slot"):
        statement = statement.where(
            Course.time_slots.is_not(None), Course.time_slots.ilike(f"%{criteria['time_slot']}%")
        )
    return statement


def _matching_rows(db: Session, criteria: dict[str, object | None]):
    statement = (
        select(Course, User.name, TeacherDB.photo_path)
        .join(User, User.id == Course.teacher_id)
        .outerjoin(TeacherDB, TeacherDB.user_id == Course.teacher_id)
        .where(Course.status == "published")
    )
    statement = _apply_required_filters(statement, criteria)
    query = criteria.get("_semantic_query")
    ordered = statement.order_by(Course.created_at.desc(), Course.id)
    if query:
        from backend.services.ai_semantic import rank_public_courses_with_status

        candidates = db.execute(ordered.limit(1001)).all()
        ranked, status = rank_public_courses_with_status(db, candidates[:1000], str(query))
        if len(candidates) > 1000:
            status = "truncated" if status == "ready" else "truncated_partial"
        return ranked[:3], status
    return db.execute(ordered.limit(3)).all(), "ready"


def _finish(db: Session, row: RecommendationSession) -> None:
    db.execute(delete(RecommendationItem).where(RecommendationItem.session_id == row.id))
    results, semantic_status = _matching_rows(db, row.criteria)
    for position, (course, _teacher_name, _photo_path) in enumerate(results):
        matched = [FIELD_LABELS[field] for field in CRITERIA_FIELDS if row.criteria.get(field) is not None]
        unknown = [
            FIELD_LABELS[field]
            for field in CRITERIA_FIELDS
            if row.criteria.get(field) is None
            and getattr(course, "price_per_lesson" if field == "max_price" else "time_slots" if field == "time_slot" else field)
            is None
        ]
        reason = f"符合你提供的{'、'.join(matched)}條件。" if matched else "這是目前已發布的鋼琴課程。"
        db.add(
            RecommendationItem(
                session_id=row.id,
                course_id=course.id,
                position=position,
                matched=matched,
                unknown=unknown,
                reason=reason,
            )
        )
    row.status = "done"
    row.question = None
    row.result_message = "找到以下符合條件的課程。" if results else "目前沒有符合這些條件的已發布課程。"
    if semantic_status == "unavailable":
        row.result_message += "語意排序暫時無法使用，目前以一般順序顯示。"
    elif semantic_status == "partial":
        row.result_message += "部分課程尚未建立語意索引，其他課程以一般順序顯示。"
    elif semantic_status in {"truncated", "truncated_partial"}:
        row.result_message += "目前僅搜尋最新的 1000 門符合條件課程。"
        if semantic_status == "truncated_partial":
            row.result_message += "部分課程的語意排序暫不可用。"
    _append_message(row, "assistant", row.result_message)


def _advance(db: Session, row: RecommendationSession, suggested_question: str = "", model_used: bool = False) -> None:
    if row.question_count < 2 and suggested_question:
        prior_questions = {m["content"] for m in row.messages if m["role"] == "assistant"}
        if suggested_question not in prior_questions:
            _ask(row, "ai_followup", suggested_question)
            return
    if model_used:
        _finish(db, row)
        return
    if row.question_count < 2:
        for field in ("level", "delivery_mode"):
            if row.criteria.get(field) is None and field not in row.asked_fields:
                _ask(row, field)
                return
    _finish(db, row)


def start_recommendation(db: Session, owner_hash: str, message: str) -> RecommendationSession:
    from backend.services import ai_model_planner

    # Expiry denies access immediately; physical deletion runs on new requests.
    db.execute(delete(RecommendationSession).where(RecommendationSession.expires_at <= datetime.now(timezone.utc)))
    row = RecommendationSession(
        owner_hash=owner_hash,
        messages=[{"role": "user", "content": message}],
        criteria={**empty_criteria(), **({} if ai_model_planner.is_configured() else parse_criteria(message))},
        asked_fields=[],
        question_count=0,
        status="asking",
        result_message="",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db.add(row)
    db.flush()
    if _unsupported(message):
        row.status = "unsupported"
        row.result_message = "目前只能協助尋找鋼琴課程。"
        _append_message(row, "assistant", row.result_message)
    else:
        planned = ai_model_planner.plan_turn(message, row.criteria)
        if planned is None and ai_model_planner.is_configured():
            db.rollback()
            raise ai_model_planner.AIPlannerUnavailable()
        if planned is not None:
            row.criteria, question = planned
        else:
            question = ""
        _advance(db, row, question, model_used=planned is not None)
    db.commit()
    db.refresh(row)
    return row


def answer_recommendation(
    db: Session, owner_hash: str, session_id: uuid.UUID, message: str
) -> RecommendationSession:
    from backend.services import ai_model_planner

    row = _load_owned(db, session_id, owner_hash, lock=True)
    if row.status not in ("asking", "done"):
        return row
    previous_question = row.question if row.status == "asking" else None
    _append_message(row, "user", message)
    criteria = dict(row.criteria)
    if not ai_model_planner.is_configured():
        criteria.update(parse_criteria(message))
    # 「不確定」代表這題已回答，但值仍是未知；asked_fields 可避免重問。
    row.criteria = criteria
    ordinal = message.strip().rstrip("。！!")
    if ordinal in {"前者", "後者"}:
        match = re.fullmatch(r"(?:你希望|你偏好|你想要|想要|你比較想)?(線上|實體)(?:上課)?(?:還是|或是)(線上|實體)(?:上課)?[?？]", previous_question or "")
        if not match or match.group(1) == match.group(2):
            db.rollback()
            raise ai_model_planner.AIPlannerUnclear()
        selected = match.group(1 if ordinal == "前者" else 2)
        criteria["delivery_mode"] = "online" if selected == "線上" else "in_person"
        planned = (criteria, "")
    elif re.fullmatch(r"(?:取消|清除)(?:曲風|風格)(?:限制|偏好)?|(?:曲風|風格)(?:不限|不限制)", ordinal):
        criteria["style"] = None
        criteria.pop("_semantic_query", None)
        planned = (criteria, "")
    else:
        planned = ai_model_planner.plan_turn(message, criteria, previous_question=previous_question)
    if planned is None and ai_model_planner.is_configured():
        db.rollback()
        raise ai_model_planner.AIPlannerUnavailable()
    if planned is not None:
        row.criteria, question = planned
    else:
        question = ""
    _advance(db, row, question, model_used=planned is not None)
    db.commit()
    db.refresh(row)
    return row


def read_recommendation(db: Session, owner_hash: str, session_id: uuid.UUID) -> RecommendationSession:
    return _load_owned(db, session_id, owner_hash)


def recommendation_items(db: Session, row: RecommendationSession) -> list[dict]:
    statement = (
        select(RecommendationItem, Course, User.name, TeacherDB.photo_path)
        .join(Course, Course.id == RecommendationItem.course_id)
        .join(User, User.id == Course.teacher_id)
        .outerjoin(TeacherDB, TeacherDB.user_id == Course.teacher_id)
        .where(RecommendationItem.session_id == row.id, Course.status == "published")
    )
    statement = _apply_required_filters(statement, row.criteria)
    records = db.execute(statement.order_by(RecommendationItem.position)).all()
    return [
        {
            "course": {
                "id": str(course.id),
                "title": course.title,
                "teacher_name": teacher_name,
                "level": course.level,
                "style": course.style,
                "delivery_mode": course.delivery_mode,
                "region": course.region,
                "price_per_lesson": course.price_per_lesson,
                "time_slots": course.time_slots,
                "description": course.description,
                "image_url": course.image_url,
                "teacher_photo_url": f"/api/images/teachers/{course.teacher_id}" if photo_path else None,
            },
            "matched": item.matched,
            "unknown": item.unknown,
            "reason": item.reason,
        }
        for item, course, teacher_name, photo_path in records
    ]
