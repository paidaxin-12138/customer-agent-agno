"""转人工后会话级 AI 锁定（6A）。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from utils.logger_loguru import get_logger

_log = get_logger("SessionHumanLock")


def lock_session_to_human(
    *,
    session_id: Optional[int] = None,
    context: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    reason: str = "",
) -> bool:
    """
    原子意图：关闭 ai_mode，刷新 metadata，中止在途 LLM turn。
    返回是否成功写入 ai_mode=False。
    """
    sid = session_id
    if sid is None:
        try:
            from database.session_store import resolve_session_id_from_context

            sid = resolve_session_id_from_context(context, metadata)
        except Exception:
            sid = None
    if sid is None:
        _log.debug("lock_session_to_human 跳过：无 session_id reason={}", reason)
        return False

    try:
        from database.session_store import lock_session_human_atomic, refresh_metadata_session

        ok = lock_session_human_atomic(int(sid))
        if metadata is not None:
            refresh_metadata_session(metadata, int(sid))
            metadata["_human_locked"] = True
            metadata["ai_mode"] = False
            metadata["_session_stage"] = "idle"
    except Exception as e:
        _log.warning("lock_session_to_human 失败 session={} reason={}: {}", sid, reason, e)
        return False

    try:
        from Message.handlers.ai_reply_watchdog import resolve_session_key

        session_key = resolve_session_key(context, metadata)
        if session_key:
            from core.turn_abort import turn_abort_registry

            turn_abort_registry.abort_active_turn(
                session_key, reason or "human_lock"
            )
    except Exception as e:
        _log.debug("lock_session_to_human abort turn: {}", e)

    if ok:
        _log.info("会话已锁定人工模式 session={} reason={}", sid, reason)
    return bool(ok)
