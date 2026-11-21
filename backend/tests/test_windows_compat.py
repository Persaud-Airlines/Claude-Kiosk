"""Platform-independent checks for the Windows / cross-platform changes."""
from __future__ import annotations

from pathlib import Path

from app.core.config import BACKEND_DIR, Settings
from app.services.timeutil import posix_tz_for


def test_relative_sqlite_path_resolves_under_backend_dir_not_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # a Windows service may start in any folder
    s = Settings(sqlite_path="data/x.db", use_sqlite=True)
    assert s.sqlite_file == BACKEND_DIR / "data" / "x.db"
    assert s.effective_database_url.startswith("sqlite+aiosqlite:///")
    assert "\\" not in s.effective_database_url  # forward slashes only, valid on Windows


def test_env_file_is_loaded_from_backend_dir():
    assert Settings.model_config["env_file"] == BACKEND_DIR / ".env"


def test_posix_tz_from_bundled_tzdata_package():
    # Windows has no system zone database; this must work from the tzdata package alone.
    assert posix_tz_for("Europe/London") == "GMT0BST,M3.5.0/1,M10.5.0"
    assert posix_tz_for("Asia/Kolkata") == "IST-5:30"


def test_restrict_to_owner_does_not_fail(tmp_path):
    from app.core.fsutil import restrict_to_owner

    f = tmp_path / "secret.txt"
    f.write_text("x", encoding="utf-8")
    restrict_to_owner(f)  # chmod on POSIX, icacls on Windows
    assert f.exists()


def test_backup_script_sqlite_roundtrip(tmp_path, monkeypatch):
    import gzip
    import sqlite3
    import sys

    sys.path.insert(0, str(Path(BACKEND_DIR / "scripts")))
    import backup  # noqa: E402

    src = tmp_path / "src.db"
    con = sqlite3.connect(src)
    con.execute("CREATE TABLE t (v TEXT)")
    con.execute("INSERT INTO t VALUES ('hello')")
    con.commit()
    con.close()
    target = tmp_path / "out.db.gz"
    backup.backup_sqlite(src, target)
    raw = gzip.open(target, "rb").read()
    out = tmp_path / "restored.db"
    out.write_bytes(raw)
    assert sqlite3.connect(out).execute("SELECT v FROM t").fetchone() == ("hello",)
