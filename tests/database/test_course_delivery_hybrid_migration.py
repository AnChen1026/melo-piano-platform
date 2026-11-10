"""Migration contract：上課方式加上 hybrid（線上或實體皆可）。"""

from __future__ import annotations

import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

UPSTREAM = "025_course_chat_starters"
REVISION = "026_course_delivery_hybrid"
SAYS_HYBRID = "鋼琴入門。\n上課方式：線上／實體皆可。"


def test_026_turns_demo_hybrid_nulls_into_hybrid_and_keeps_other_nulls(migration_database: tuple[Config, Engine]) -> None:
    config, engine = migration_database
    command.upgrade(config, UPSTREAM)
    teacher_id = uuid.uuid4()
    cases = {
        "demo_hybrid": (None, SAYS_HYBRID, "hybrid"),
        "teacher_left_blank": (None, "老師沒填上課方式", None),
        "online_with_sentence": ("online", SAYS_HYBRID, "online"),
        "in_person": ("in_person", None, "in_person"),
    }
    ids = {name: uuid.uuid4() for name in cases}
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id, email, password_hash, name, role) VALUES (:id, :email, 'x', 'T', 'teacher')"),
            {"id": teacher_id, "email": f"teacher-{teacher_id}@example.test"},
        )
        for name, (mode, description, _expected) in cases.items():
            connection.execute(
                text(
                    "INSERT INTO courses (id, teacher_id, title, status, delivery_mode, description) "
                    "VALUES (:id, :teacher_id, 'Mode Course', 'published', :mode, :description)"
                ),
                {"id": ids[name], "teacher_id": teacher_id, "mode": mode, "description": description},
            )

    command.upgrade(config, REVISION)

    with engine.connect() as connection:
        stored = dict(connection.execute(text("SELECT id, delivery_mode FROM courses")).all())
    assert {name: stored[ids[name]] for name in cases} == {name: case[2] for name, case in cases.items()}
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("UPDATE courses SET delivery_mode = 'home_visit' WHERE id = :id"), {"id": ids["in_person"]})

    command.downgrade(config, UPSTREAM)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT delivery_mode FROM courses WHERE id = :id"), {"id": ids["demo_hybrid"]}).scalar_one() is None
