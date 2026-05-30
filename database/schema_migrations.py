"""
SQLite 增量 schema 补丁（与 Alembic revision 0001 共用）。
旧库通过 create_all 不会自动补列，此处幂等执行 ALTER / 一次性数据修正。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Optional

from sqlalchemy.engine import Engine


def _db_path(engine: Engine) -> Optional[str]:
    return engine.url.database


def migrate_chat_session_memory_columns(engine: Engine, logger: Any = None) -> int:
    path = _db_path(engine)
    if not path:
        return 0
    conn = sqlite3.connect(path)
    applied = 0
    try:
        cur = conn.execute("PRAGMA table_info(chat_sessions)")
        cols = {row[1] for row in cur.fetchall()}
        alters = []
        if "task_state_json" not in cols:
            alters.append("ALTER TABLE chat_sessions ADD COLUMN task_state_json TEXT")
        if "long_term_summary" not in cols:
            alters.append("ALTER TABLE chat_sessions ADD COLUMN long_term_summary TEXT")
        if "memory_summary_through_id" not in cols:
            alters.append(
                "ALTER TABLE chat_sessions ADD COLUMN memory_summary_through_id INTEGER DEFAULT 0"
            )
        for sql in alters:
            conn.execute(sql)
            applied += 1
        if alters:
            conn.commit()
            if logger:
                logger.info(f"chat_sessions 记忆字段迁移: {applied} 列")
    except Exception as e:
        if logger:
            logger.warning(f"chat_sessions 记忆字段迁移失败: {e}")
    finally:
        conn.close()
    return applied


def migrate_merchant_refund_apply_columns(engine: Engine, logger: Any = None) -> int:
    path = _db_path(engine)
    if not path:
        return 0
    conn = sqlite3.connect(path)
    applied = 0
    try:
        cur = conn.execute("PRAGMA table_info(merchant_refund_apply_logs)")
        cols = {row[1] for row in cur.fetchall()}
        if not cols:
            return 0
        alters = []
        if "status" not in cols:
            alters.append(
                "ALTER TABLE merchant_refund_apply_logs ADD COLUMN status TEXT"
            )
        if "valid_time_unix" not in cols:
            alters.append(
                "ALTER TABLE merchant_refund_apply_logs "
                "ADD COLUMN valid_time_unix INTEGER"
            )
        for sql in alters:
            conn.execute(sql)
            applied += 1
        if alters:
            conn.commit()
            if logger:
                logger.info(f"merchant_refund_apply_logs 迁移: {applied} 列")
    except Exception as e:
        if logger:
            logger.warning(f"merchant_refund_apply_logs 迁移失败: {e}")
    finally:
        conn.close()
    return applied


def migrate_ops_schema(engine: Engine, logger: Any = None) -> int:
    try:
        from database.ops_migrate import migrate_ops_schema

        path = _db_path(engine)
        if path:
            return migrate_ops_schema(path)
    except Exception as e:
        if logger:
            logger.warning(f"ops 表迁移跳过: {e}")
    return 0


def migrate_utc_timestamps_to_shanghai(engine: Engine, logger: Any = None) -> int:
    path = _db_path(engine)
    if not path:
        return 0
    conn = sqlite3.connect(path)
    n = 0
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        row = conn.execute(
            "SELECT value FROM app_meta WHERE key='timestamps_shanghai_v1'"
        ).fetchone()
        if row and str(row[0]) == "1":
            return 0
        patches = [
            ("chat_sessions", ("updated_at", "created_at")),
            ("chat_messages", ("created_at", "read_at")),
            ("ops_sessions", ("updated_at",)),
            ("ops_traces", ("created_at",)),
            ("ops_knowledge_revisions", ("created_at",)),
            ("ops_low_confidence", ("updated_at",)),
            ("ops_tickets", ("created_at", "updated_at")),
            ("ops_eval_runs", ("created_at",)),
            ("ops_cost_logs", ("created_at",)),
            ("ops_security_audits", ("created_at",)),
        ]
        for table, cols in patches:
            for col in cols:
                try:
                    cur = conn.execute(
                        f"UPDATE {table} SET {col} = datetime({col}, '+8 hours') "
                        f"WHERE {col} IS NOT NULL"
                    )
                    n += cur.rowcount
                except sqlite3.OperationalError:
                    pass
        conn.execute(
            "INSERT OR REPLACE INTO app_meta (key, value) VALUES "
            "('timestamps_shanghai_v1', '1')"
        )
        conn.commit()
        if n > 0 and logger:
            logger.info(f"时间字段 UTC→上海迁移: 约 {n} 行")
    except Exception as e:
        if logger:
            logger.warning(f"时间迁移失败: {e}")
    finally:
        conn.close()
    return n


def apply_legacy_migrations(engine: Engine, logger: Any = None) -> int:
    """幂等执行全部遗留补丁，返回大致变更计数。"""
    total = 0
    total += migrate_chat_session_memory_columns(engine, logger)
    total += migrate_merchant_refund_apply_columns(engine, logger)
    total += migrate_ops_schema(engine, logger)
    total += migrate_utc_timestamps_to_shanghai(engine, logger)
    return total
