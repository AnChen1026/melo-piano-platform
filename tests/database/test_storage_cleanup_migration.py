from sqlalchemy import inspect

from alembic import command


def test_storage_cleanup_upgrade_downgrade(migration_database):
    config, engine = migration_database
    command.upgrade(config, "016_storage_cleanup")
    assert "storage_cleanup_jobs" in inspect(engine).get_table_names()
    command.downgrade(config, "015_studios")
    assert "storage_cleanup_jobs" not in inspect(engine).get_table_names()
    assert "teacher_studios" in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    assert "storage_cleanup_jobs" in inspect(engine).get_table_names()


def test_both_existing_heads_upgrade_to_merged_head(migration_database):
    from alembic.script import ScriptDirectory

    config, engine = migration_database
    command.upgrade(config, "015_studios")
    for previous in ("016_storage_cleanup", "016_metronome_score"):
        command.upgrade(config, previous)
        command.upgrade(config, "head")
        assert ScriptDirectory.from_config(config).get_current_head() == "023_course_delivery_mode"
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "023_course_delivery_mode"
        inspector = inspect(engine)
        assert "storage_cleanup_jobs" in inspector.get_table_names()
        assert "availability_slots" in inspector.get_table_names()
        assert "course_embeddings" in inspector.get_table_names()
        assert "score_sheet_path" in {c["name"] for c in inspector.get_columns("practice_feedbacks")}
        assert "metronome_bpm" in {c["name"] for c in inspector.get_columns("practice_recordings")}
        command.downgrade(config, "015_studios")
