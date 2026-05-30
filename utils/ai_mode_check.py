"""会话 ai_mode 查询：带重试与失败监控，避免瞬时 DB 故障误关 AI。"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from bridge.context import Context
from config import config
from utils.logger_loguru import get_logger

_logger = get_logger("AiModeCheck")

_fail_count = 0
_recover_count = 0


def get_ai_mode_check_stats() -> Dict[str, int]:
    return {"fail": _fail_count, "recovered_after_retry": _recover_count}


def _resolve_buyer_uid(context: Context, metadata: Dict[str, Any]) -> Optional[str]:
    uid = metadata.get("from_uid")
    if uid:
        return str(uid)
    try:
        ku = getattr(context, "kwargs", None)
        if ku and getattr(ku, "from_uid", None):
            return str(getattr(ku, "from_uid"))
    except Exception:
        pass
    return None


def _check_once(
    channel_name: str,
    shop_id: str,
    user_id: str,
    buyer_uid: str,
) -> Optional[bool]:
    """
    查询 ai_mode；返回 None 表示无法判定（缺账号/会话），由调用方决定默认。
    返回 True/False 为明确结果。
    """
    from database.db_manager import db_manager

    acc = db_manager.get_account(channel_name, shop_id, user_id)
    if not acc or not acc.get("id"):
        return None
    sess = db_manager.get_chat_session_by_buyer(int(acc["id"]), buyer_uid, "active")
    if not sess:
        return None
    return bool(sess.get("ai_mode", True))


def is_ai_mode_enabled(context: Context, metadata: Dict[str, Any]) -> bool:
    """
    是否允许 AI 回复。缺字段时默认 True；DB 连续失败时按配置 fail_open 或关闭。
    """
    global _fail_count, _recover_count

    channel_name = str(metadata.get("channel_name") or "pinduoduo")
    shop_id = str(metadata.get("shop_id") or "")
    user_id = str(metadata.get("user_id") or "")
    buyer_uid = _resolve_buyer_uid(context, metadata)
    if not all([shop_id, user_id, buyer_uid]):
        return True

    retries = int(config.get("chat.ai_mode_check_retries", 3) or 3)
    retries = max(1, min(retries, 5))
    delay = float(config.get("chat.ai_mode_check_retry_delay_sec", 0.12) or 0.12)
    delay = max(0.05, min(delay, 1.0))
    fail_open = bool(config.get("chat.ai_mode_check_fail_open", False))

    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            result = _check_once(channel_name, shop_id, user_id, str(buyer_uid))
            if attempt > 1:
                _recover_count += 1
                _logger.info(
                    "ai_mode 检查第 {} 次重试成功 buyer={}",
                    attempt,
                    buyer_uid,
                )
            if result is None:
                return True
            return result
        except Exception as e:
            last_err = e
            if attempt < retries:
                _logger.debug(
                    "ai_mode 检查失败 ({}/{}): {}，{}s 后重试",
                    attempt,
                    retries,
                    e,
                    delay,
                )
                time.sleep(delay)
            else:
                _fail_count += 1
                _logger.warning(
                    "ai_mode 检查 {} 次均失败 buyer={} fail_open={}: {}",
                    retries,
                    buyer_uid,
                    fail_open,
                    e,
                )
                try:
                    from core.ops_telemetry import record_ai_mode_check_failure

                    record_ai_mode_check_failure(str(e), metadata)
                except Exception:
                    pass
                return fail_open

    if last_err:
        return fail_open
    return True
