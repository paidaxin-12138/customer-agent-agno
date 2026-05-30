import sqlite3
from pathlib import Path

from scripts.backup_db import backup_database


def test_backup_database_roundtrip(tmp_path):
    src = tmp_path / "src.db"
    conn = sqlite3.connect(src)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t (v) VALUES ('x')")
    conn.commit()
    conn.close()

    dest_dir = tmp_path / "backup"
    out = backup_database(db_path=src, backup_dir=dest_dir, retention_days=7)
    assert out.exists()
    conn2 = sqlite3.connect(out)
    row = conn2.execute("SELECT v FROM t").fetchone()
    conn2.close()
    assert row[0] == "x"
