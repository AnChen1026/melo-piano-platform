"""Import the fictional AICourseFinder catalog into local/staging only.
Stable UUIDs preserve identities; optional refresh updates known versions of the demo catalog.
"""

import argparse
import json
import uuid
from pathlib import Path

from sqlalchemy import insert, select

from backend.models.student import Course
from backend.models.teacher import TeacherDB
from backend.models.teacher_application import TeacherApplication
from backend.models.user import User
from backend.services.course import check_course_fields

from scripts.demo_catalog import (
    REFRESH_FIELDS, PROFILE_FIELDS, content_fingerprint, profile_fingerprint,
    course_description, course_fields, teacher_fields,
)

namespace = uuid.uuid5(uuid.NAMESPACE_URL, "aipe04/local/aicourse-demo-import/v1")


def identity(kind, key):
    return uuid.uuid5(namespace, kind + ":" + key)




def _snapshot(record, names):
    return {name: getattr(record, name) for name in names}


def _known_versions():
    return json.loads((Path(__file__).parent / "data/aicourse-demo-versions.json").read_text(encoding="utf-8"))


def import_demo(db, source, *, refresh_existing=False, known_versions=None):
    if any(not r.get("is_demo") for r in source["teachers"] + source["courses"]):
        raise ValueError("Only fictional demo records are allowed")
    for group in ("teachers", "courses"):
        ids = [r["id"] for r in source[group]]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate source IDs")
    teachers = {t["id"]: t for t in source["teachers"]}
    for c in source["courses"]:
        key = c["public_teacher_id"] or c["teacher_id"]
        if key not in teachers:
            teachers[key] = {
                "id": key,
                "display_name": c["teacher_name"],
                "biography": c["teaching_profile"],
                "teaching_style": "",
                "specialties": c["goals"],
                "years_experience": None,
            }
    teacher_ids = [identity("teacher", key) for key in teachers]
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(teacher_ids)))}
    profiles = {
        p.user_id: p
        for p in db.scalars(select(TeacherDB).where(TeacherDB.user_id.in_(teacher_ids)))
    }
    applications = set(db.scalars(
        select(TeacherApplication.user_id).where(TeacherApplication.user_id.in_(teacher_ids))
    ))
    course_ids = [identity("course", c["id"]) for c in source["courses"]]
    courses = {c.id: c for c in db.scalars(select(Course).where(Course.id.in_(course_ids)))}
    versions = known_versions if known_versions is not None else _known_versions()
    # Validate every existing row before making any change. A collision must not
    # leave half a refresh in the caller's session, even before rollback.
    for key, teacher in teachers.items():
        uid = identity("teacher", key)
        existing = users.get(uid)
        if existing is not None:
            allowed_names = {teacher["display_name"]}
            if refresh_existing:
                allowed_names.update(versions["teachers"].get(key, []))
            if (
                existing.email != f"aicourse-{uid.hex}@example.invalid"
                or existing.name not in allowed_names
                or existing.role != "teacher"
                or existing.password_hash is not None
            ):
                raise ValueError("Demo user ID collision; nothing should be committed")
        profile = profiles.get(uid)
        if refresh_existing and profile is not None:
            current = profile_fingerprint(_snapshot(profile, PROFILE_FIELDS))
            allowed = set(versions.get("profiles", {}).get(key, []))
            allowed.add(profile_fingerprint(teacher_fields(teacher)))
            if current not in allowed:
                raise ValueError("Demo profile ID collision; nothing should be committed")
    for course in source["courses"]:
        if course["instrument"] != "piano" or not course["is_demo"]:
            raise ValueError("Unexpected non-demo or non-piano record")
        fields = check_course_fields(course_fields(course))
        existing = courses.get(identity("course", course["id"]))
        if existing is not None:
            current = content_fingerprint(_snapshot(existing, REFRESH_FIELDS))
            allowed = {content_fingerprint(fields)}
            if refresh_existing:
                allowed.update(versions["courses"].get(course["id"], []))
            key = course["public_teacher_id"] or course["teacher_id"]
            if existing.teacher_id != identity("teacher", key) or current not in allowed:
                raise ValueError("Demo course ID collision; nothing should be committed")
    created = {"users": 0, "profiles": 0, "applications": 0, "courses": 0}
    for key, t in teachers.items():
        uid = identity("teacher", key)
        existing = users.get(uid)
        if existing is not None and refresh_existing:
            existing.name = t["display_name"]
        if existing is None:
            db.execute(insert(User).values(
                id=uid, email=f"aicourse-{uid.hex}@example.invalid",
                name=t["display_name"], role="teacher", is_active=True,
                auth_provider="password", password_hash=None,
            ))
            created["users"] += 1
    db.flush()
    for key, t in teachers.items():
        uid = identity("teacher", key)
        if uid not in profiles:
            db.add(
                TeacherDB(
                    id=identity("profile", key),
                    user_id=uid,
                    gender="未提供",
                    seniority=t["years_experience"],
                    **teacher_fields(t),
                    target_learning=t.get("target_learning"),
                    status="active",
                )
            )
            created["profiles"] += 1
        if refresh_existing and uid in profiles:
            profile = profiles[uid]
            for name, value in teacher_fields(t).items():
                setattr(profile, name, value)
            if profile.target_learning is None:
                profile.target_learning = t.get("target_learning")
        if uid not in applications:
            db.add(
                TeacherApplication(
                    id=identity("application", key),
                    user_id=uid,
                    teaching_subjects="鋼琴",
                    teaching_experience="舊 AICourseFinder 虛構測試資料，非真實資格。",
                    bio=t["biography"],
                    status="approved",
                    review_note="本機假資料搬移，非真實老師審核。",
                )
            )
            created["applications"] += 1
    db.flush()
    for c in source["courses"]:
        cid = identity("course", c["id"])
        fields = check_course_fields(course_fields(c))
        existing = courses.get(cid)
        if existing is not None:
            if refresh_existing:
                for name in REFRESH_FIELDS:
                    setattr(existing, name, fields[name])
            continue
        key = c["public_teacher_id"] or c["teacher_id"]
        db.add(Course(id=cid, teacher_id=identity("teacher", key), **fields))
        created["courses"] += 1
    db.flush()
    return created


def main():
    from sqlalchemy.engine import make_url

    from backend.core.config import get_database_url, read_env_value
    from backend.core.database import SessionLocal

    parser = argparse.ArgumentParser(
        description="Insert fictional catalog; dry-run by default"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--refresh-existing", action="store_true",
        help="Refresh known demo catalog versions (names, profiles, titles, levels, styles, descriptions)",
    )
    parser.add_argument("--confirm-database")
    args = parser.parse_args()
    env = read_env_value("APP_ENV") or "local"
    url = make_url(get_database_url())
    if env not in {"local", "staging"}:
        parser.error("Demo imports are limited to local/staging")
    if url.host not in {"localhost", "127.0.0.1", "postgres"} and env != "staging":
        parser.error("Remote imports require APP_ENV=staging")
    if args.apply and args.confirm_database != url.database:
        parser.error("--apply requires --confirm-database matching target database")
    source = json.loads((Path(__file__).parent / "data/aicourse-demo.json").read_text(encoding="utf-8"))
    with SessionLocal() as db:
        try:
            # Serialize repeated imports without affecting normal website writes.
            from sqlalchemy import text

            db.execute(text("SELECT pg_advisory_xact_lock(426226)"))
            counts = import_demo(db, source, refresh_existing=args.refresh_existing)
            if args.apply:
                db.commit()
            else:
                db.rollback()
        except Exception:
            db.rollback()
            raise
    print(
        json.dumps(
            {"mode": "apply" if args.apply else "dry-run", "created": counts},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
