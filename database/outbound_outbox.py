"""
出站 Outbox：pending → processing → sent / failed / dead。

- UPDATE ... RETURNING 原子认领 pending/failed
- 发送路径单次尝试，失败由 worker 按 retry_count 重试（≥3 次 dead + 告警）
- (session_id, buyer_msg_id, channel_name) 唯一防重复入队
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

from config import get_config
from database.sqlite_outbox import connect_sqlite
from utils.logger_loguru import get_logger

_log = get_logger("OutboundOutbox")

_STATUS_PENDING = "pending"
_STATUS_PROCESSING = "processing"
_STATUS_SENT = "sent"
_STATUS_FAILED = "failed"
_STATUS_DEAD = "dead"


def _db_path() -> Optional[str]:
    try:
        p = get_config("db_path")
        if p:
            from utils.runtime_path import resolve_writable_path

            return str(resolve_writable_path(str(p)))
    except Exception:
        pass
    return None


def _connect() -> sqlite3.Connection:
    import sqlite3

    path = _db_path()
    if not path:
        raise sqlite3.OperationalError("outbox db_path 未配置")
    return connect_sqlite(path)


def outbox_enabled() -> bool:
    return bool(get_config("chat.outbound_outbox_enabled", True))


def _max_retry_count() -> int:
    try:
        return max(1, min(int(get_config("chat.outbound_outbox_max_attempts", 3) or 3), 10))
    except (TypeError, ValueError):
        return 3


def _retry_interval_sec() -> float:
    try:
        return max(10.0, float(get_config("chat.outbound_outbox_retry_interval_sec", 60) or 60))
    except (TypeError, ValueError):
        return 60.0


def _processing_timeout_sec() -> float:
    try:
        return max(
            60.0,
            float(get_config("chat.outbound_outbox_processing_timeout_sec", 300) or 300),
        )
    except (TypeError, ValueError):
        return 300.0


def _row_to_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return dict(row)
    return dict(row)


def create_pending(
    *,
    session_id: int,
    account_id: int,
    channel_name: str,
    shop_id: str,
    user_id: str,
    buyer_uid: str,
    content: str,
    buyer_msg_id: str = "",
    sender_type: str = "ai",
    login_username: str = "",
    message_kind: str = "text",
    payload: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """写入 pending；同 (session_id, buyer_msg_id, channel) 已存在则返回已有 id。"""
    if not outbox_enabled():
        return None
    body = str(content or "").strip()
    if not body or not session_id or not account_id:
        return None
    path = _db_path()
    if not path:
        return None
    kind = str(message_kind or "text").strip() or "text"
    ch = str(channel_name or "pinduoduo")
    bmid = str(buyer_msg_id or "").strip()
    payload_json: Optional[str] = None
    if payload:
        try:
            payload_json = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            payload_json = None
    now = time.time()
    max_retry = _max_retry_count()
    try:
        conn = _connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO outbound_outbox (
                    session_id, account_id, channel_name, shop_id, user_id,
                    buyer_uid, buyer_msg_id, login_username, content, message_kind,
                    payload_json, sender_type, status, attempts, max_attempts,
                    retry_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 0, ?)
                ON CONFLICT(session_id, buyer_msg_id, channel_name) DO NOTHING
                RETURNING id
                """,
                (
                    int(session_id),
                    int(account_id),
                    ch,
                    str(shop_id),
                    str(user_id),
                    str(buyer_uid),
                    bmid,
                    str(login_username or ""),
                    body,
                    kind,
                    payload_json,
                    str(sender_type or "ai"),
                    _STATUS_PENDING,
                    max_retry,
                    now,
                ),
            )
            row = cur.fetchone()
            if row:
                conn.commit()
                return int(row[0])
            existing = conn.execute(
                """
                SELECT id FROM outbound_outbox
                WHERE session_id = ? AND buyer_msg_id = ? AND channel_name = ?
                ORDER BY id DESC LIMIT 1
                """,
                (int(session_id), bmid, ch),
            ).fetchone()
            if existing:
                return int(existing[0])
        finally:
            conn.close()
    except Exception as e:
        _log.warning("create_pending 失败 session={}: {}", session_id, e)
        return None
    return None


def _claim_sql_where(account_id: Optional[int], due_before: float) -> tuple[str, list[Any]]:
    max_retry = _max_retry_count()
    clauses = [
        "status IN (?, ?)",
        "retry_count < ?",
        "(last_attempt_at IS NULL OR last_attempt_at <= ?)",
    ]
    params: List[Any] = [
        _STATUS_PENDING,
        _STATUS_FAILED,
        max_retry,
        due_before,
    ]
    if account_id is not None:
        clauses.append("account_id = ?")
        params.append(int(account_id))
    return " AND ".join(clauses), params


def claim_by_id(outbox_id: int) -> Optional[Dict[str, Any]]:
    """按 id 原子认领 pending/failed → processing（UPDATE RETURNING）。"""
    if not outbox_id:
        return None
    now = time.time()
    try:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(
                """
                UPDATE outbound_outbox
                SET status = ?,
                    processing_at = ?,
                    last_attempt_at = ?
                WHERE id = ?
                  AND status IN (?, ?)
                  AND retry_count < ?
                RETURNING *
                """,
                (
                    _STATUS_PROCESSING,
                    now,
                    now,
                    int(outbox_id),
                    _STATUS_PENDING,
                    _STATUS_FAILED,
                    _max_retry_count(),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_dict(row) if row else None
        finally:
            conn.close()
    except Exception as e:
        _log.debug("claim_by_id 失败 id={}: {}", outbox_id, e)
        return None


def claim_for_send(outbox_id: int) -> bool:
    """兼容旧调用：认领成功返回 True。"""
    return claim_by_id(int(outbox_id)) is not None


def _claim_next_due(*, account_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """原子认领下一条 due 的 pending/failed（UPDATE RETURNING）。"""
    now = time.time()
    due_before = now - _retry_interval_sec()
    where_sql, params = _claim_sql_where(account_id, due_before)
    try:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(
                f"""
                UPDATE outbound_outbox
                SET status = ?,
                    processing_at = ?,
                    last_attempt_at = ?
                WHERE id = (
                    SELECT id FROM outbound_outbox
                    WHERE {where_sql}
                    ORDER BY created_at ASC
                    LIMIT 1
                )
                  AND status IN (?, ?)
                  AND retry_count < ?
                RETURNING *
                """,
                (
                    _STATUS_PROCESSING,
                    now,
                    now,
                    *params,
                    _STATUS_PENDING,
                    _STATUS_FAILED,
                    _max_retry_count(),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_dict(row) if row else None
        finally:
            conn.close()
    except Exception as e:
        _log.debug("claim_next_due 失败: {}", e)
        return None


def claim_due_outbox(
    *,
    account_id: Optional[int] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """回收超时 processing 后，批量原子认领 due 记录。"""
    reset_stale_processing()
    lim = max(1, min(int(limit), 50))
    rows: List[Dict[str, Any]] = []
    for _ in range(lim):
        row = _claim_next_due(account_id=account_id)
        if not row:
            break
        rows.append(row)
    return rows


def mark_sent(outbox_id: int, *, chat_message_id: Optional[int] = None) -> None:
    path = _db_path()
    if not path or not outbox_id:
        return
    now = time.time()
    try:
        conn = _connect()
        try:
            conn.execute(
                """
                UPDATE outbound_outbox
                SET status = ?, sent_at = ?, chat_message_id = ?,
                    error_detail = NULL, processing_at = NULL
                WHERE id = ?
                """,
                (_STATUS_SENT, now, chat_message_id, int(outbox_id)),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        _log.debug("mark_sent 失败 id={}: {}", outbox_id, e)


def _sanitize_error_detail(error: str) -> str:
    from utils.log_redact import redact_string_value

    return str(redact_string_value(str(error or "")))[:500]


def mark_abandoned(outbox_id: int, reason: str = "") -> None:
    """业务上不可再试（如退货卡门禁），标记 dead 且不触发 dead 告警。"""
    path = _db_path()
    if not path or not outbox_id:
        return
    err = _sanitize_error_detail(reason)
    try:
        conn = _connect()
        try:
            conn.execute(
                """
                UPDATE outbound_outbox
                SET status = ?, error_detail = ?, processing_at = NULL
                WHERE id = ?
                """,
                (_STATUS_DEAD, err, int(outbox_id)),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        _log.debug("mark_abandoned 失败 id={}: {}", outbox_id, e)


def mark_failed(outbox_id: int, error: str = "") -> str:
    """发送失败：retry_count+1；≥max 则 dead 并告警。返回最终 status。"""
    path = _db_path()
    if not path or not outbox_id:
        return _STATUS_FAILED
    err = _sanitize_error_detail(error)
    final = _STATUS_FAILED
    max_retry = _max_retry_count()
    try:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(
                """
                UPDATE outbound_outbox
                SET retry_count = retry_count + 1,
                    attempts = retry_count + 1,
                    error_detail = ?,
                    processing_at = NULL,
                    status = CASE
                        WHEN retry_count + 1 >= ? THEN ?
                        ELSE ?
                    END
                WHERE id = ? AND status = ?
                RETURNING status, retry_count
                """,
                (
                    err,
                    max_retry,
                    _STATUS_DEAD,
                    _STATUS_FAILED,
                    int(outbox_id),
                    _STATUS_PROCESSING,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            if row:
                final = str(row[0])
                if final == _STATUS_DEAD:
                    _log.error("出站 outbox 进入 dead id={} err={}", outbox_id, err)
                    try:
                        from core.human_assist_bus import emit_outbox_dead_alert

                        dead_row = get_row(int(outbox_id))
                        if dead_row:
                            emit_outbox_dead_alert(dead_row)
                    except Exception as alert_err:
                        _log.debug("outbox dead 告警跳过 id={}: {}", outbox_id, alert_err)
            return final
        finally:
            conn.close()
    except Exception as e:
        _log.debug("mark_failed 失败 id={}: {}", outbox_id, e)
    return final


def reset_stale_processing(max_age_sec: Optional[float] = None) -> int:
    """将超时卡在 processing 的记录退回 failed（不增加 retry_count）。"""
    path = _db_path()
    if not path:
        return 0
    age = float(max_age_sec if max_age_sec is not None else _processing_timeout_sec())
    cutoff = time.time() - max(60.0, age)
    try:
        conn = _connect()
        try:
            cur = conn.execute(
                """
                UPDATE outbound_outbox
                SET status = ?, processing_at = NULL
                WHERE status = ?
                  AND (
                    (processing_at IS NOT NULL AND processing_at < ?)
                    OR (processing_at IS NULL AND last_attempt_at IS NOT NULL
                        AND last_attempt_at < ?)
                  )
                """,
                (_STATUS_FAILED, _STATUS_PROCESSING, cutoff, cutoff),
            )
            conn.commit()
            n = int(cur.rowcount or 0)
            if n:
                _log.warning("outbox 回收超时 processing 记录 {} 条", n)
            return n
        finally:
            conn.close()
    except Exception as e:
        _log.debug("reset_stale_processing: {}", e)
        return 0


def fetch_due_retries(
    *,
    account_id: Optional[int] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """兼容：返回已原子认领的 due 行（发送侧勿再 claim）。"""
    return claim_due_outbox(account_id=account_id, limit=limit)


def session_has_active_outbox(session_id: int) -> bool:
    """会话是否存在未完成的出站（含 pending/processing/failed 可重试）。"""
    if not session_id or not outbox_enabled():
        return False
    path = _db_path()
    if not path:
        return False
    max_retry = _max_retry_count()
    try:
        conn = _connect()
        try:
            row = conn.execute(
                """
                SELECT 1 FROM outbound_outbox
                WHERE session_id = ?
                  AND (
                    status IN (?, ?)
                    OR (status = ? AND retry_count < ?)
                  )
                LIMIT 1
                """,
                (
                    int(session_id),
                    _STATUS_PENDING,
                    _STATUS_PROCESSING,
                    _STATUS_FAILED,
                    max_retry,
                ),
            ).fetchone()
            return row is not None
        finally:
            conn.close()
    except Exception as e:
        _log.debug("session_has_active_outbox: {}", e)
        return False


def get_row(outbox_id: int) -> Optional[Dict[str, Any]]:
    path = _db_path()
    if not path or not outbox_id:
        return None
    try:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM outbound_outbox WHERE id = ?",
                (int(outbox_id),),
            ).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            conn.close()
    except Exception:
        return None
