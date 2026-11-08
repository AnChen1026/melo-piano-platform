"""Migration contract for course delivery mode values."""

from __future__ import annotations

import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text


UPSTREAM_REVISION = "022_quiz_generation_jobs"
DELIVERY_MODE_REVISION = "023_course_delivery_mode"


def test_023_maps_chinese_values_and_clears_unknown(migration_database: tuple[Config, Engine]) -> None:
    config, engine = migration_database
    command.upgrade(config, UPSTREAM_REVISION)
    teacher_id = uuid.uuid4()
    values = {"線上": "online", "實體": "in_person", "線上與實體": "in_person", "hybrid": None, "online": "online", None: None}
    course_ids = {}
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id, email, password_hash, name, role) VALUES (:id, :email, 'x', 'T', 'teacher')"),
            {"id": teacher_id, "email": f"teacher-{teacher_id}@example.test"},
        )
        for value in values:
            course_ids[value] = uuid.uuid4()
            connection.execute(
                text(
                    "INSERT INTO courses (id, teacher_id, title, status, delivery_mode) "
                    "VALUES (:id, :teacher_id, 'Mode Course', 'draft', :mode)"
                ),
                {"id": course_ids[value], "teacher_id": teacher_id, "mode": value},
            )

    command.upgrade(config, DELIVERY_MODE_REVISION)

    with engine.connect() as connection:
        stored = dict(connection.execute(text("SELECT id, delivery_mode FROM courses")).all())
    assert {value: stored[course_id] for value, course_id in course_ids.items()} == values
