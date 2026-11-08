"""Restore only into a new, network-isolated disposable PostgreSQL container."""

import json
import subprocess
import time
import uuid
from pathlib import Path

from psycopg import sql

from scripts.ops.backup import verify_bundle
from scripts.ops.common import OpsError, atomic_json, utcnow
from scripts.ops.database_refs import file_columns
from scripts.ops.postgres import POSTGRES_IMAGE


def execute(args, timeout=180):
    result = subprocess.run(
        args,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise OpsError("isolated_restore_command_failed")
    return result.stdout.decode()


def restore_check(settings, bundle):
    bundle = Path(bundle).resolve()
    manifest = verify_bundle(bundle)
    if manifest["source_id"] != settings.source_id:
        raise OpsError("backup_source_mismatch")
    name = "aipe04-restore-" + uuid.uuid4().hex[:16]
    docker = settings.docker
    created = False
    try:
        execute(
            [
                docker,
                "run",
                "--rm",
                "-d",
                "--name",
                name,
                "--network",
                "none",
                "--memory",
                "768m",
                "--cpus",
                "1",
                "-e",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                "-e",
                "POSTGRES_DB=restore_test",
                "-v",
                str(bundle) + ":/restore:ro",
                POSTGRES_IMAGE,
            ]
        )
        created = True
        for _ in range(30):
            result = subprocess.run(
                [
                    docker,
                    "exec",
                    name,
                    "pg_isready",
                    "-U",
                    "postgres",
                    "-d",
                    "restore_test",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise OpsError("isolated_database_not_ready")
        # 備份只含 public schema；向量欄位的型別在 extensions schema（Supabase 的慣例），
        # 要先建好，pg_restore 才認得 extensions.vector。
        execute(
            [
                docker,
                "exec",
                name,
                "psql",
                "-U",
                "postgres",
                "-d",
                "restore_test",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                (
                    "CREATE SCHEMA IF NOT EXISTS extensions; "
                    "CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;"
                ),
            ]
        )
        execute(
            [
                docker,
                "exec",
                name,
                "pg_restore",
                "-U",
                "postgres",
                "--no-owner",
                "--no-acl",
                "--clean",
                "--if-exists",
                "-d",
                "restore_test",
                "/restore/database.dump",
            ]
        )

        def query(statement):
            return json.loads(
                execute(
                    [
                        docker,
                        "exec",
                        name,
                        "psql",
                        "-U",
                        "postgres",
                        "-d",
                        "restore_test",
                        "-At",
                        "-c",
                        statement,
                    ]
                )
            )

        expressions = []
        for table in manifest["database"]["row_counts"]:
            expressions.extend(
                [
                    sql.Literal(table),
                    sql.SQL("(SELECT count(*) FROM public.{})").format(
                        sql.Identifier(table)
                    ),
                ]
            )
        statement = (
            sql.SQL("SELECT json_build_object({})")
            .format(sql.SQL(",").join(expressions))
            .as_string()
        )
        counts = query(statement)
        if counts != manifest["database"]["row_counts"]:
            raise OpsError("restored_row_counts_mismatch")
        revision = query("SELECT to_json(version_num) FROM public.alembic_version")
        if revision != manifest["database"]["revision"]:
            raise OpsError("restored_revision_mismatch")
        reference_selects = [
            sql.SQL(
                "SELECT {field} AS value FROM public.{table} WHERE {field} IS NOT NULL"
            ).format(field=sql.Identifier(field), table=sql.Identifier(table))
            for table, field in file_columns(revision)
        ]
        refs = query(
            sql.SQL("SELECT coalesce(json_agg(value),'[]'::json) FROM ({}) AS refs")
            .format(sql.SQL(" UNION ").join(reference_selects))
            .as_string()
        )
        if set(refs) != set(manifest["database"]["references"]):
            raise OpsError("restored_file_references_mismatch")
        result = {
            "status": "success",
            "source_id": settings.source_id,
            "bundle": bundle.name,
            "finished_at": utcnow().isoformat(),
            "tables_verified": len(counts),
            "objects_verified": len(manifest["objects"]),
            "file_references_verified": len(refs),
        }
        atomic_json(settings.state_dir / "restore-status.json", result)
        return result
    finally:
        if created:
            subprocess.run(
                [docker, "rm", "-f", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
