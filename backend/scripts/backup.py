#!/usr/bin/env python3
"""Back up the database on macOS, Linux or Windows.

  SQLite:      consistent online copy (sqlite3 backup API, safe while the server runs), gzip-compressed
  PostgreSQL:  pg_dump custom-format archive (needs pg_dump on PATH, or set PG_DUMP to its full path)

Backups contain student data. They are written to backend\\backups (or BACKUP_DIR) and restricted to
the owner / SYSTEM / Administrators. Keep that folder on an encrypted drive (BitLocker).

  python scripts/backup.py            # KEEP_DAYS (default 30) of backups are retained
"""
from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.fsutil import restrict_to_owner  # noqa: E402


def backup_sqlite(src_path: Path, target: Path) -> None:
    tmp = target.with_suffix("")  # ...db.gz -> ...db
    src = sqlite3.connect(str(src_path))
    try:
        dst = sqlite3.connect(str(tmp))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    with open(tmp, "rb") as fin, gzip.open(target, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    tmp.unlink()


def backup_postgres(database_url: str, target: Path) -> None:
    url = make_url(database_url.replace("+asyncpg", ""))
    pg_dump = os.environ.get("PG_DUMP") or shutil.which("pg_dump")
    if not pg_dump:
        raise SystemExit("pg_dump not found: install PostgreSQL client tools or set PG_DUMP")
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = url.password
    cmd = [pg_dump, "--format=custom", f"--file={target}", f"--host={url.host or 'localhost'}",
           f"--port={url.port or 5432}", f"--username={url.username or 'postgres'}", url.database or "detechtive"]
    subprocess.run(cmd, env=env, check=True)


def main() -> int:
    s = get_settings()
    dest = Path(os.environ.get("BACKUP_DIR") or BACKEND / "backups")
    keep_days = int(os.environ.get("KEEP_DAYS", "30"))
    dest.mkdir(parents=True, exist_ok=True)
    restrict_to_owner(dest)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    if s.use_sqlite:
        target = dest / f"detechtive-{stamp}.db.gz"
        backup_sqlite(s.sqlite_file, target)
    else:
        target = dest / f"detechtive-{stamp}.dump"
        backup_postgres(s.database_url, target)
    restrict_to_owner(target)
    print(f"backup written: {target}")

    cutoff = time.time() - keep_days * 86400
    for old in dest.glob("detechtive-*"):
        if old.is_file() and old.stat().st_mtime < cutoff:
            old.unlink()
            print(f"removed old backup: {old.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
