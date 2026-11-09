# Alembic 啟動時讀取 DATABASE_URL，並使用現有 SQLAlchemy Model。
# 不要在這裡寫死帳密。

import sys
from pathlib import Path

# backend/alembic/env.py 的上一層再上一層，本機是專案根目錄，Docker 裡是 /app。
project_root = str(Path(__file__).resolve().parents[2])
if project_root not in sys.path:
    sys.path.insert(0, project_root)
    
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.core.config import get_database_url
from backend.models.base import Base
from backend.models.course_embedding import CourseEmbedding  # noqa: F401
from backend.models.rag_document import RagDocument  # noqa: F401
from backend.models.course_chat_starter import CourseChatStarter  # noqa: F401
from backend.models.user import User  # noqa: F401
from backend.models.teacher_application import TeacherApplication  # noqa: F401
from backend.models.password_reset import PasswordResetRequest  # noqa: F401
from backend.models.auth_identity import AuthIdentity  # noqa: F401
from backend.models.material import MaterialDB  # noqa: F401
from backend.models.quiz import QuizDB  # noqa: F401
from backend.models.student import (  # noqa: F401
    Course,
    RecommendationItem,
    RecommendationSession,
    ReferenceMidi,
)
from backend.models.teacher import TeacherDB  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = get_database_url()
alembic_database_url = database_url.replace("%", "%%")
config.set_main_option("sqlalchemy.url", alembic_database_url)

target_metadata = Base.metadata


def run_migrations_offline():
    """只產生 SQL，不真正連線資料庫。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """連線 PostgreSQL 並執行 migration。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
