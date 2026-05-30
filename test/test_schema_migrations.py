import sqlite3
from pathlib import Path

from sqlalchemy import create_engine

from database.schema_migrations import migrate_chat_session_memory_columns


def test_memory_columns_idempotent(tmp_path):
    db = tmp_path / "t.db"
    engine = create_engine(f"sqlite:///{db}")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE chat_sessions (id INTEGER PRIMARY KEY, account_id INTEGER)")
    conn.commit()
    conn.close()
    n1 = migrate_chat_session_memory_columns(engine)
    assert n1 >= 1
    n2 = migrate_chat_session_memory_columns(engine)
    assert n2 == 0
