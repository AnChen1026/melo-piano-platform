"""Load an ignored JSON environment without shell interpolation or secret output.

Example: python -m scripts.cloud_command --config .env.cloud.json seed
"""

import argparse
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(".env.cloud.json"))
    parser.add_argument(
        "command", choices=["validate", "migrate", "seed", "migrate-files", "cleanup", "index-courses", "chat-starters"]
    )
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    values = json.loads(args.config.read_text())
    allowed = {
        "APP_ENV",
        "DATABASE_URL",
        "STORAGE_BACKEND",
        "SUPABASE_URL",
        "SUPABASE_SECRET_KEY",
        "SUPABASE_DB_CA_CERT",
        "SESSION_HTTPS_ONLY",
        "SESSION_SECRET_KEY",
    }
    if (
        not isinstance(values, dict)
        or set(values) - allowed
        or not all(isinstance(v, str) for v in values.values())
    ):
        parser.error(
            "Configuration must contain only documented cloud setting names and string values"
        )
    os.environ.update(values)
    from scripts.validate_cloud_config import validate

    validate()
    if args.command == "validate":
        print("Cloud configuration validated (secrets hidden).")
        return
    if args.command == "migrate":
        if args.arguments:
            parser.error("migrate accepts no additional arguments")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                "backend/alembic.ini",
                "upgrade",
                "head",
            ],
            check=True,
        )
        return
    module = {
        "seed": "scripts.import_demo_data",
        "migrate-files": "scripts.migrate_uploads",
        "cleanup": "scripts.retry_storage_cleanup",
        "index-courses": "scripts.index_course_embeddings",
        "chat-starters": "scripts.chat_starters",
    }[args.command]
    sys.argv = [module, *args.arguments]
    runpy.run_module(module, run_name="__main__")


if __name__ == "__main__":
    main()
