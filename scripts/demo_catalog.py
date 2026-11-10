"""Pure catalog presentation and version fingerprints, shared by build/import QA."""

import hashlib
import json

LEVELS = {"intro": "入門", "beginner": "初階", "intermediate": "中階", "advanced": "進階"}
GOALS = {"classical": "古典", "pop": "流行", "accompaniment": "伴奏", "exam": "檢定", "interest": "興趣"}
SLOTS = {
    "weekday_day": "平日白天", "weekday_evening": "平日晚上",
    "weekend_morning": "週末上午", "weekend_afternoon": "週末下午",
    "weekend_evening": "週末晚上",
}
REFRESH_FIELDS = ("title", "level", "style", "description")


def course_description(course):
    audience = {"adult": "成人", "child": "兒童"}.get(course["audience"], course["audience"])
    return "\n".join(filter(None, [
        course["description"], course["teaching_profile"],
        f"對象：{audience}；每堂 {course['duration_minutes']} 分鐘。",
        "上課方式：線上／實體皆可。" if course["delivery_mode"] == "hybrid" else "",
    ]))


def course_fields(course):
    return {
        "title": course["title"], "level": LEVELS[course["level"]],
        "style": course.get("style") or "、".join(GOALS[g] for g in course["goals"]),
        "delivery_mode": {"online": "online", "onsite": "in_person", "hybrid": "hybrid"}[course["delivery_mode"]],
        "region": course["area"], "price_per_lesson": course["price_amount"],
        "time_slots": "、".join(SLOTS[s] for s in course["slots"]),
        "status": course["status"], "description": course_description(course),
    }


def content_fingerprint(fields):
    """Only the four editable catalog fields; scheduling/media/status stay untouched."""
    content = {key: fields.get(key) for key in REFRESH_FIELDS}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


PROFILE_FIELDS = ("name", "expertise", "short_intros", "teaching_method")


def teacher_fields(teacher):
    return {
        "name": teacher["display_name"],
        "expertise": "、".join(GOALS.get(g, g) for g in teacher["specialties"]),
        "short_intros": teacher["biography"][:200],
        "teaching_method": teacher["teaching_style"][:255],
    }


def profile_fingerprint(fields):
    return hashlib.sha256(json.dumps(
        {key: fields.get(key) for key in PROFILE_FIELDS},
        ensure_ascii=False, sort_keys=True,
    ).encode()).hexdigest()
