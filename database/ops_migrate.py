"""运营看板 SQLite 表结构迁移（create_all 不会给旧表补列）。"""

from __future__ import annotations

import sqlite3
from typing import Dict, List, Tuple

from utils.logger_loguru import get_logger

logger = get_logger("OpsMigrate")

# table -> [(column_name, sqlite_type), ...]
_OPS_COLUMN_PATCHES: Dict[str, List[Tuple[str, str]]] = {
    "ops_sessions": [
        ("chat_session_id", "INTEGER"),
        ("session_key", "TEXT"),
        ("user_label", "TEXT"),
        ("channel", "TEXT"),
        ("intent", "TEXT"),
        ("status", "TEXT"),
        ("is_resolved", "INTEGER"),
        ("transferred_to_human", "INTEGER"),
        ("updated_at", "TEXT"),
    ],
}


def migrate_ops_schema(db_path: str) -> int:
    """为已有 ops_* 表补齐缺失列。返回执行的 ALTER 数量。"""
    if not db_path:
        return 0
    conn = sqlite3.connect(db_path)
    applied = 0
    try:
        for table, patches in _OPS_COLUMN_PATCHES.items():
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
            if not cur.fetchone():
                continue
            cur = conn.execute(f"PRAGMA table_info({table})")
            existing = {row[1] for row in cur.fetchall()}
            for col, col_type in patches:
                if col in existing:
                    continue
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                applied += 1
                logger.info(f"ops 迁移: {table}.{col}")
        if applied:
            conn.commit()
    except Exception as e:
        logger.warning(f"ops 表结构迁移失败: {e}")
    finally:
        conn.close()
    return applied
