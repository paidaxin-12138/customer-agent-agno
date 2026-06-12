"""
出站 Outbox：pending → processing → sent / failed / dead。

先发 MMS 前落库，崩溃后补偿只重试发送，不重新走 LLM。
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

from config import get_config
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


def outbox_enabled() -> bool:
    return bool(get_config("chat.outbound_outbox_enabled", True))


def _max_attempts() -> int:
    try:
        return max(1, min(int(get_config("chat.outbound_outbox_max_attempts", 3) or 3), 10))
    except (TypeError, ValueError):
        return 3


def _retry_interval_sec() -> float:
    try:
        return max(10.0, float(get_config("chat.outbound_outbox_retry_interval_sec", 60) or 60))
    except (TypeError, ValueError):
        return 60.0


def create_pending(
    *,
    session_id: int,
    account_id: int,
    channel_name: str,
    shop_id: str,
    user_id: str,
    buyer_uid: str,
    content: str,
    sender_type: str = "ai",
    login_username: str = "",
    message_kind: str = "text",
    payload: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """写入 pending 出站记录，返回 outbox id。"""
    if not outbox_enabled():
        return None
    body = str(content or "").strip()
    if not body or not session_id or not account_id:
        return None
    path = _db_path()
    if not path:
        return None
    kind = str(message_kind or "text").strip() or "text"
    payload_json: Optional[str] = None
    if payload:
        try:
            payload_json = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            payload_json = None
    now = time.time()
    try:
        conn = sqlite3.connect(path, timeout=30.0)
        try:
            cur = conn.execute(
                """
                INSERT INTO outbound_outbox (
                    session_id, account_id, channel_name, shop_id, user_id,
                    buyer_uid, login_username, content, message_kind, payload_json,
                    sender_type, status, attempts, max_attempts, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    int(session_id),
                    int(account_id),
                    str(channel_name or "pinduoduo"),
                    str(shop_id),
                    str(user_id),
                    str(buyer_uid),
                    str(login_username or ""),
                    body,
                    kind,
                    payload_json,
                    str(sender_type or "ai"),
                    _STATUS_PENDING,
                    _max_attempts(),
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()
    except Exception as e:
        _log.warning("create_pending 失败 session={}: {}", session_id, e)
        return None


def claim_for_send(outbox_id: int) -> bool:
    """pending/failed → processing（乐观锁）。"""
    path = _db_path()
    if not path or not outbox_id:
        return False
    now = time.time()
    try:
        conn = sqlite3.connect(path, timeout=30.0)
        try:
            cur = conn.execute(
                """
                UPDATE outbound_outbox
                SET status = ?, last_attempt_at = ?, attempts = attempts + 1
                WHERE id = ? AND status IN (?, ?)
                """,
                (
                    _STATUS_PROCESSING,
                    now,
                    int(outbox_id),
                    _STATUS_PENDING,
                    _STATUS_FAILED,
                ),
            )
            conn.commit()
            return cur.rowcount == 1
        finally:
            conn.close()
    except Exception as e:
        _log.debug("claim_for_send 失败 id={}: {}", outbox_id, e)
        return False


def mark_sent(outbox_id: int, *, chat_message_id: Optional[int] = None) -> None:
    path = _db_path()
    if not path or not outbox_id:
        return
    now = time.time()
    try:
        conn = sqlite3.connect(path, timeout=30.0)
        try:
            conn.execute(
                """
                UPDATE outbound_outbox
                SET status = ?, sent_at = ?, chat_message_id = ?, error_detail = NULL
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
        conn = sqlite3.connect(path, timeout=30.0)
        try:
            conn.execute(
                """
                UPDATE outbound_outbox
                SET status = ?, error_detail = ?
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
    """标记 failed 或 dead；返回最终 status。"""
    path = _db_path()
    if not path or not outbox_id:
        return _STATUS_FAILED
    err = _sanitize_error_detail(error)
    final = _STATUS_FAILED
    try:
        conn = sqlite3.connect(path, timeout=30.0)
        try:
            row = conn.execute(
                "SELECT attempts, max_attempts FROM outbound_outbox WHERE id = ?",
                (int(outbox_id),),
            ).fetchone()
            if row and int(row[0] or 0) >= int(row[1] or _max_attempts()):
                final = _STATUS_DEAD
            conn.execute(
                """
                UPDATE outbound_outbox
                SET status = ?, error_detail = ?
                WHERE id = ?
                """,
                (final, err, int(outbox_id)),
            )
            conn.commit()
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


def reset_stale_processing(max_age_sec: float = 300.0) -> int:
    """将长时间卡在 processing 的记录退回 failed。"""
    path = _db_path()
    if not path:
        return 0
    cutoff = time.time() - max(30.0, float(max_age_sec))
    try:
        conn = sqlite3.connect(path, timeout=30.0)
        try:
            cur = conn.execute(
                """
                UPDATE outbound_outbox
                SET status = ?
                WHERE status = ? AND last_attempt_at < ?
                """,
                (_STATUS_FAILED, _STATUS_PROCESSING, cutoff),
            )
            conn.commit()
            return int(cur.rowcount or 0)
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
    """取出待重试的 pending/failed 记录（单条 LIMIT）。"""
    path = _db_path()
    if not path:
        return []
    reset_stale_processing()
    now = time.time()
    interval = _retry_interval_sec()
    due_before = now - interval
    lim = max(1, min(int(limit), 50))
    try:
        conn = sqlite3.connect(path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            if account_id is not None:
                rows = conn.execute(
                    """
                    SELECT * FROM outbound_outbox
                    WHERE account_id = ?
                      AND status IN (?, ?)
                      AND attempts < max_attempts
                      AND (last_attempt_at IS NULL OR last_attempt_at <= ?)
                    ORDER BY created_at ASC
                    LIMIT ?
                    """,
                    (
                        int(account_id),
                        _STATUS_PENDING,
                        _STATUS_FAILED,
                        due_before,
                        lim,
                    ),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM outbound_outbox
                    WHERE status IN (?, ?)
                      AND attempts < max_attempts
                      AND (last_attempt_at IS NULL OR last_attempt_at <= ?)
                    ORDER BY created_at ASC
                    LIMIT ?
                    """,
                    (_STATUS_PENDING, _STATUS_FAILED, due_before, lim),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception as e:
        _log.debug("fetch_due_retries: {}", e)
        return []


def session_has_active_outbox(session_id: int) -> bool:
    """会话是否存在未完成的出站（含 pending/processing/failed 可重试）。"""
    if not session_id or not outbox_enabled():
        return False
    path = _db_path()
    if not path:
        return False
    try:
        conn = sqlite3.connect(path, timeout=30.0)
        try:
            row = conn.execute(
                """
                SELECT 1 FROM outbound_outbox
                WHERE session_id = ?
                  AND (
                    status IN (?, ?)
                    OR (status = ? AND attempts < max_attempts)
                  )
                LIMIT 1
                """,
                (
                    int(session_id),
                    _STATUS_PENDING,
                    _STATUS_PROCESSING,
                    _STATUS_FAILED,
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
        conn = sqlite3.connect(path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM outbound_outbox WHERE id = ?",
                (int(outbox_id),),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    except Exception:
        return None
