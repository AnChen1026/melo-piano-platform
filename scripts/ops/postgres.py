"""Read-only snapshots and PostgreSQL client operations via isolated Docker."""

import os
import subprocess
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg import sql

from scripts.ops.common import OpsError
from scripts.ops.database_refs import file_columns

# 和 docker-compose 的資料庫同一個映像：PostgreSQL 17.11（Debian 13）＋ pgvector。
# 從 024 起資料表用到 extensions.vector 型別，還原時資料庫必須有這個擴充功能。
POSTGRES_IMAGE = "pgvector/pgvector:0.8.1-pg17-trixie"


class Postgres:
    def __init__(self, settings):
        self.settings = settings

    @contextmanager
    def snapshot(self):
        with psycopg.connect(**self.settings.pg, autocommit=True) as conn:
            if conn.info.server_version // 10000 != 17:
                raise OpsError("postgres_major_version_must_be_17")
            conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            try:
                snapshot = conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
                names = [
                    row[0]
                    for row in conn.execute(
                        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
                    )
                ]
                if "alembic_version" not in names:
                    raise OpsError("application_schema_missing")
                counts = {
                    name: conn.execute(
                        sql.SQL("SELECT count(*) FROM public.{}").format(
                            sql.Identifier(name)
                        )
                    ).fetchone()[0]
                    for name in names
                }
                revisions = conn.execute(
                    "SELECT version_num FROM public.alembic_version"
                ).fetchall()
                if len(revisions) != 1:
                    raise OpsError("application_schema_requires_single_head")
                revision = revisions[0][0]
                refs = set()
                for table, field in file_columns(revision):
                    if table not in names:
                        raise OpsError("application_schema_incomplete")
                    query = sql.SQL(
                        "SELECT {field} FROM public.{table} WHERE {field} IS NOT NULL"
                    ).format(
                        field=sql.Identifier(field),
                        table=sql.Identifier(table),
                    )
                    for (value,) in conn.execute(query):
                        if not value.startswith("storage://"):
                            raise OpsError("local_file_reference_in_cloud_database")
                        refs.add(value)
                yield (
                    snapshot,
                    {
                        "row_counts": counts,
                        "references": sorted(refs),
                        "revision": revision,
                    },
                )
            finally:
                conn.execute("ROLLBACK")

    def dump(self, target, snapshot):
        s = self.settings
        env = os.environ.copy()
        env["PGPASSWORD"] = s.pg["password"]
        args = [
            s.docker,
            "run",
            "--rm",
            "-e",
            "PGPASSWORD",
            "-e",
            "PGSSLMODE=verify-full",
            "-e",
            "PGSSLROOTCERT=/certs/root.crt",
            "-e",
            "PGCONNECT_TIMEOUT=15",
            "-v",
            s.pg["sslrootcert"] + ":/certs/root.crt:ro",
            POSTGRES_IMAGE,
            "pg_dump",
            "-h",
            s.pg["host"],
            "-p",
            str(s.pg["port"]),
            "-U",
            s.pg["user"],
            "-d",
            s.pg["dbname"],
            "--snapshot=" + snapshot,
            "--schema=public",
            "--no-owner",
            "--no-acl",
            "--format=custom",
        ]
        with Path(target).open("xb") as output:
            Path(target).chmod(0o600)
            result = subprocess.run(
                args,
                env=env,
                stdout=output,
                stderr=subprocess.PIPE,
                timeout=1800,
                check=False,
            )
        if result.returncode:
            raise OpsError("database_dump_failed")
        self.verify_dump(target)

    def verify_dump(self, target):
        args = [
            self.settings.docker,
            "run",
            "--rm",
            "-v",
            str(Path(target).resolve()) + ":/backup/database.dump:ro",
            POSTGRES_IMAGE,
            "pg_restore",
            "--list",
            "/backup/database.dump",
        ]
        result = subprocess.run(
            args,
            capture_output=True,
            timeout=60,
            check=False,
        )
        if result.returncode or not result.stdout:
            raise OpsError("database_dump_invalid")
