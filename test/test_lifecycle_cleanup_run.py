# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""生命周期清理入口。"""
import sqlite3
from pathlib import Path
from unittest.mock import patch


def test_run_lifecycle_cleanup_empty_db(tmp_path, monkeypatch):
    db = tmp_path / "agent.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute(
        "CREATE TABLE chat_messages ("
        "id INTEGER PRIMARY KEY, session_id INTEGER, created_at TEXT, "
        "sender_type TEXT, content TEXT)"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr("core.lifecycle_cleanup._db_path", lambda: Path(db))
    monkeypatch.setattr(
        "core.lifecycle_cleanup._retention_cfg",
        lambda: {
            "chat_history_days": 365,
            "audit_log_days": 365,
            "temp_files_days": 7,
            "vacuum_interval_days": 9999,
        },
    )
    monkeypatch.setattr(
        "core.lifecycle_cleanup.clean_old_vector_docs",
        lambda **_kw: 0,
    )

    from core.lifecycle_cleanup import run_lifecycle_cleanup

    stats = run_lifecycle_cleanup()
    assert isinstance(stats, dict)
