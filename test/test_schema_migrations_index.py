"""chat_messages 未读索引迁移。"""
import sqlite3

from sqlalchemy import create_engine

from database.schema_migrations import migrate_chat_messages_unread_index


def test_unread_index_idempotent(tmp_path):
    db = tmp_path / "t.db"
    engine = create_engine(f"sqlite:///{db}")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE chat_messages ("
        "id INTEGER PRIMARY KEY, session_id INTEGER, sender_type TEXT, is_read INTEGER)"
    )
    conn.commit()
    conn.close()

    assert migrate_chat_messages_unread_index(engine) == 1
    assert migrate_chat_messages_unread_index(engine) == 0

    conn = sqlite3.connect(db)
    names = {row[1] for row in conn.execute("PRAGMA index_list(chat_messages)")}
    assert "idx_chat_messages_unread" in names
    conn.close()
