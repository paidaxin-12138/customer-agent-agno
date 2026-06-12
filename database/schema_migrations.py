# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
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
        if "inbound_transferred_at" not in cols:
            alters.append(
                "ALTER TABLE chat_sessions ADD COLUMN inbound_transferred_at DATETIME"
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


def migrate_chat_messages_unread_index(engine: Engine, logger: Any = None) -> int:
    """未读统计复合索引，加速 _count_unread_buyer_messages_bulk。"""
    path = _db_path(engine)
    if not path:
        return 0
    conn = sqlite3.connect(path)
    try:
        cur = conn.execute("PRAGMA index_list(chat_messages)")
        names = {row[1] for row in cur.fetchall()}
        if "idx_chat_messages_unread" in names:
            return 0
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_messages_unread "
            "ON chat_messages (session_id, sender_type, is_read)"
        )
        conn.commit()
        if logger:
            logger.info("chat_messages 未读复合索引已创建")
        return 1
    except Exception as e:
        if logger:
            logger.warning(f"chat_messages 索引迁移失败: {e}")
        return 0
    finally:
        conn.close()


def migrate_message_dead_letters_table(engine: Engine, logger: Any = None) -> int:
    path = _db_path(engine)
    if not path:
        return 0
    conn = sqlite3.connect(path)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='message_dead_letters'"
        )
        if cur.fetchone():
            return 0
        conn.execute(
            """
            CREATE TABLE message_dead_letters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                queue_name TEXT NOT NULL,
                context_json TEXT NOT NULL,
                reason TEXT,
                from_uid TEXT,
                msg_id TEXT,
                created_at REAL NOT NULL,
                replayed_at REAL,
                status TEXT NOT NULL DEFAULT 'pending'
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mdl_queue_status "
            "ON message_dead_letters (queue_name, status)"
        )
        conn.commit()
        if logger:
            logger.info("message_dead_letters 表已创建")
        return 1
    except Exception as e:
        if logger:
            logger.warning(f"message_dead_letters 迁移失败: {e}")
        return 0
    finally:
        conn.close()


def migrate_outbound_outbox_table(engine: Engine, logger: Any = None) -> int:
    path = _db_path(engine)
    if not path:
        return 0
    conn = sqlite3.connect(path)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='outbound_outbox'"
        )
        if cur.fetchone():
            return 0
        conn.execute(
            """
            CREATE TABLE outbound_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                channel_name TEXT NOT NULL DEFAULT 'pinduoduo',
                shop_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                buyer_uid TEXT NOT NULL,
                login_username TEXT,
                content TEXT NOT NULL,
                message_kind TEXT NOT NULL DEFAULT 'text',
                payload_json TEXT,
                sender_type TEXT NOT NULL DEFAULT 'ai',
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                last_attempt_at REAL,
                error_detail TEXT,
                chat_message_id INTEGER,
                created_at REAL NOT NULL,
                sent_at REAL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbox_retry "
            "ON outbound_outbox (status, last_attempt_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbox_session "
            "ON outbound_outbox (session_id, status)"
        )
        conn.commit()
        if logger:
            logger.info("outbound_outbox 表已创建")
        return 1
    except Exception as e:
        if logger:
            logger.warning(f"outbound_outbox 迁移失败: {e}")
        return 0
    finally:
        conn.close()


def migrate_outbound_outbox_kind_columns(engine: Engine, logger: Any = None) -> int:
    path = _db_path(engine)
    if not path:
        return 0
    conn = sqlite3.connect(path)
    applied = 0
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='outbound_outbox'"
        )
        if not cur.fetchone():
            return 0
        cur = conn.execute("PRAGMA table_info(outbound_outbox)")
        cols = {row[1] for row in cur.fetchall()}
        alters = []
        if "message_kind" not in cols:
            alters.append(
                "ALTER TABLE outbound_outbox "
                "ADD COLUMN message_kind TEXT NOT NULL DEFAULT 'text'"
            )
        if "payload_json" not in cols:
            alters.append(
                "ALTER TABLE outbound_outbox ADD COLUMN payload_json TEXT"
            )
        for sql in alters:
            conn.execute(sql)
            applied += 1
        if alters:
            conn.commit()
            if logger:
                logger.info(f"outbound_outbox 扩展列迁移: {applied} 列")
    except Exception as e:
        if logger:
            logger.warning(f"outbound_outbox 扩展列迁移失败: {e}")
    finally:
        conn.close()
    return applied


def apply_legacy_migrations(engine: Engine, logger: Any = None) -> int:
    """幂等执行全部遗留补丁，返回大致变更计数。"""
    total = 0
    total += migrate_chat_session_memory_columns(engine, logger)
    total += migrate_merchant_refund_apply_columns(engine, logger)
    total += migrate_ops_schema(engine, logger)
    total += migrate_utc_timestamps_to_shanghai(engine, logger)
    total += migrate_chat_messages_unread_index(engine, logger)
    total += migrate_message_dead_letters_table(engine, logger)
    total += migrate_outbound_outbox_table(engine, logger)
    total += migrate_outbound_outbox_kind_columns(engine, logger)
    return total
