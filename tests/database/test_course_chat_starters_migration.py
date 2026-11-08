"""Migration contract for AI course chat starter questions."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_025_creates_starters_with_category_check(migration_database: tuple[Config, Engine]) -> None:
    config, engine = migration_database
    command.upgrade(config, "025_course_chat_starters")
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO course_chat_starters (id, text, category) VALUES (gen_random_uuid(), '問題', 'criteria')")
        )
        assert connection.execute(text("SELECT is_active FROM course_chat_starters")).scalar_one() is False
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text("INSERT INTO course_chat_starters (id, text, category) VALUES (gen_random_uuid(), '別的', 'other')")
        )
    command.downgrade(config, "024_pgvector_rag")
    assert "course_chat_starters" not in inspect(engine).get_table_names()
