"""队列满时消息 dead-letter 持久化与重放。"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

from bridge.context import Context
from config import get_config
from utils.logger_loguru import get_logger

_log = get_logger("MessageDeadLetter")

_STATUS_PENDING = "pending"
_STATUS_REPLAYED = "replayed"
_STATUS_FAILED = "failed"
_STATUS_SKIPPED_DEDUP = "skipped_dedup"


def _db_path() -> Optional[str]:
    try:
        from config import get_config as _cfg

        return str(_cfg("db_path") or "").strip() or None
    except Exception:
        return None


def _dead_letter_enabled() -> bool:
    try:
        return bool(get_config("chat.dead_letter_enabled", True))
    except Exception:
        return True


def _replay_batch_limit() -> int:
    try:
        v = int(get_config("chat.dead_letter_replay_batch", 20) or 20)
        return max(1, min(v, 200))
    except (TypeError, ValueError):
        return 20


def _retention_days() -> int:
    try:
        v = int(get_config("retention.dead_letter_days", 14) or 14)
        return max(1, min(v, 365))
    except (TypeError, ValueError):
        return 14


def _context_to_json(context: Context) -> str:
    if hasattr(context, "model_dump"):
        payload = context.model_dump(mode="json")
    else:
        payload = context.dict()
    return json.dumps(payload, ensure_ascii=False)


def _context_from_json(raw: str) -> Context:
    data = json.loads(raw)
    return Context.model_validate(data)


def _extract_meta(context: Context) -> tuple[str, str]:
    from_uid = ""
    msg_id = ""
    try:
        ku = getattr(context, "kwargs", None)
        if ku is not None:
            from_uid = str(getattr(ku, "from_uid", "") or "")
            msg_id = str(getattr(ku, "msg_id", "") or "")
    except Exception:
        pass
    return from_uid, msg_id


def persist_dead_letter(
    queue_name: str,
    context: Context,
    *,
    reason: str = "queue_full",
) -> Optional[int]:
    """将未能入队的 Context 写入 SQLite dead-letter 表。"""
    if not _dead_letter_enabled():
        return None
    path = _db_path()
    if not path:
        _log.warning("dead-letter 跳过：无 db_path")
        return None
    from_uid, msg_id = _extract_meta(context)
    now = time.time()
    try:
        conn = sqlite3.connect(path)
        try:
            cur = conn.execute(
                """
                INSERT INTO message_dead_letters
                    (queue_name, context_json, reason, from_uid, msg_id, created_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(queue_name),
                    _context_to_json(context),
                    str(reason or "queue_full"),
                    from_uid,
                    msg_id,
                    now,
                    _STATUS_PENDING,
                ),
            )
            conn.commit()
            letter_id = int(cur.lastrowid)
            try:
                from core.app_metrics import record_queue_dead_letter

                record_queue_dead_letter(queue_name)
            except Exception:
                pass
            _log.warning(
                "消息已写入 dead-letter id={} queue={} from_uid={} reason={}",
                letter_id,
                queue_name,
                from_uid,
                reason,
            )
            return letter_id
        finally:
            conn.close()
    except Exception as exc:
        _log.error("dead-letter 持久化失败 queue={}: {}", queue_name, exc)
        return None


def _fetch_pending(queue_name: str, limit: int) -> List[Dict[str, Any]]:
    path = _db_path()
    if not path:
        return []
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT id, queue_name, context_json, reason, from_uid, msg_id, created_at
            FROM message_dead_letters
            WHERE queue_name = ? AND status = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (str(queue_name), _STATUS_PENDING, int(limit)),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def _mark_status(letter_id: int, status: str) -> None:
    path = _db_path()
    if not path:
        return
    now = time.time()
    conn = sqlite3.connect(path)
    try:
        if status == _STATUS_REPLAYED:
            conn.execute(
                """
                UPDATE message_dead_letters
                SET status = ?, replayed_at = ?
                WHERE id = ?
                """,
                (status, now, int(letter_id)),
            )
        else:
            conn.execute(
                "UPDATE message_dead_letters SET status = ? WHERE id = ?",
                (status, int(letter_id)),
            )
        conn.commit()
    finally:
        conn.close()


def persist_ws_frame_dead_letter(
    queue_name: str,
    raw_frame: object,
    *,
    reason: str = "ws_inflight_cancel",
) -> Optional[int]:
    """WS 在途帧被取消时写入 dead-letter（原始帧 JSON 包装）。"""
    if not _dead_letter_enabled():
        return None
    path = _db_path()
    if not path:
        return None
    try:
        raw_text = raw_frame if isinstance(raw_frame, str) else str(raw_frame)
    except Exception:
        raw_text = repr(raw_frame)
    wrapper = {
        "_dead_letter_kind": "ws_raw_frame",
        "raw": raw_text[:100_000],
    }
    now = time.time()
    try:
        conn = sqlite3.connect(path)
        try:
            cur = conn.execute(
                """
                INSERT INTO message_dead_letters
                    (queue_name, context_json, reason, from_uid, msg_id, created_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(queue_name),
                    json.dumps(wrapper, ensure_ascii=False),
                    str(reason or "ws_inflight_cancel"),
                    "",
                    "",
                    now,
                    _STATUS_PENDING,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()
    except Exception as exc:
        _log.error("WS frame dead-letter 失败 queue={}: {}", queue_name, exc)
        return None


async def replay_pending_for_queue(queue_name: str) -> int:
    """消费者启动后尝试重放 pending dead-letter；成功入队则标记 replayed。"""
    if not _dead_letter_enabled():
        return 0
    from Message.core.queue import queue_manager

    rows = _fetch_pending(queue_name, _replay_batch_limit())
    if not rows:
        return 0
    replayed = 0
    for row in rows:
        letter_id = int(row["id"])
        raw_json = str(row["context_json"])
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict) and parsed.get("_dead_letter_kind") == "ws_raw_frame":
                _mark_status(letter_id, _STATUS_FAILED)
                _log.debug("dead-letter {} WS 原始帧跳过重放", letter_id)
                continue
        except json.JSONDecodeError:
            pass
        try:
            context = _context_from_json(raw_json)
        except Exception as exc:
            _log.warning("dead-letter {} 反序列化失败: {}", letter_id, exc)
            _mark_status(letter_id, _STATUS_FAILED)
            continue
        queue = queue_manager.get_or_create_queue(queue_name)
        try:
            msg_id = await queue.put(context)
        except RuntimeError as exc:
            if "Queue is full" in str(exc):
                _log.debug(
                    "dead-letter {} 重放时队列仍满，稍后重试 queue={}",
                    letter_id,
                    queue_name,
                )
                break
            _mark_status(letter_id, _STATUS_FAILED)
            _log.warning("dead-letter {} 重放失败: {}", letter_id, exc)
            continue
        except Exception as exc:
            _mark_status(letter_id, _STATUS_FAILED)
            _log.warning("dead-letter {} 重放异常: {}", letter_id, exc)
            continue
        if not msg_id:
            _mark_status(letter_id, _STATUS_SKIPPED_DEDUP)
            _log.debug(
                "dead-letter {} 重放被去重跳过 queue={}",
                letter_id,
                queue_name,
            )
            continue
        _mark_status(letter_id, _STATUS_REPLAYED)
        replayed += 1
        _log.info(
            "dead-letter {} 已重放入队 queue={} wrapper_id={}",
            letter_id,
            queue_name,
            msg_id,
        )
    if replayed:
        _log.info("dead-letter 重放完成 queue={} count={}", queue_name, replayed)
    return replayed


def list_pending_queue_names(limit: int = 50) -> List[str]:
    path = _db_path()
    if not path:
        return []
    conn = sqlite3.connect(path)
    try:
        cur = conn.execute(
            """
            SELECT DISTINCT queue_name
            FROM message_dead_letters
            WHERE status = ?
            ORDER BY queue_name ASC
            LIMIT ?
            """,
            (_STATUS_PENDING, max(1, min(int(limit), 200))),
        )
        return [str(row[0]) for row in cur.fetchall() if row[0]]
    finally:
        conn.close()


def count_pending() -> int:
    path = _db_path()
    if not path:
        return 0
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM message_dead_letters WHERE status = ?",
            (_STATUS_PENDING,),
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def purge_old_dead_letters(retention_days: Optional[int] = None) -> int:
    """删除已重放/失败且超过保留期的 dead-letter 记录。"""
    if not _dead_letter_enabled():
        return 0
    path = _db_path()
    if not path:
        return 0
    days = retention_days if retention_days is not None else _retention_days()
    cutoff = time.time() - days * 86400
    conn = sqlite3.connect(path)
    try:
        cur = conn.execute(
            """
            DELETE FROM message_dead_letters
            WHERE status IN (?, ?) AND created_at < ?
            """,
            (_STATUS_REPLAYED, _STATUS_FAILED, cutoff),
        )
        conn.commit()
        removed = int(cur.rowcount or 0)
        if removed:
            _log.info("dead-letter 清理 {} 条（保留 {} 天）", removed, days)
        return removed
    except Exception as exc:
        _log.warning("dead-letter 清理失败: {}", exc)
        return 0
    finally:
        conn.close()
