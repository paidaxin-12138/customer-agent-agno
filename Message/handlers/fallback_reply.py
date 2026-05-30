"""
处理器链未成功回复买家时的统一安抚（可配置开关与文案）。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Set

from bridge.context import Context, ContextType
from config import config
from utils.logger_loguru import get_logger

_logger = get_logger("FallbackReply")

# 买家通常期待文字回复的消息类型
_REPLY_EXPECTED_TYPES: Set[ContextType] = {
    ContextType.TEXT,
    ContextType.GOODS_INQUIRY,
    ContextType.GOODS_SPEC,
    ContextType.ORDER_INFO,
    ContextType.EMOTION,
    ContextType.GOODS_CARD,
}


def _default_notice() -> str:
    return (
        "亲，消息已收到，客服稍后会回复您；如需人工请回复「人工」。"
    )


def should_attempt_fallback(context: Context) -> bool:
    if not bool(config.get("chat.unhandled_fallback_enabled", True)):
        return False
    try:
        return context.type in _REPLY_EXPECTED_TYPES
    except Exception:
        return False


async def try_send_unhandled_fallback(
    context: Context,
    metadata: Dict[str, Any],
) -> bool:
    """向买家发送统一安抚；缺少会话字段或发送失败时返回 False。"""
    if not should_attempt_fallback(context):
        return False

    shop_id = metadata.get("shop_id")
    user_id = metadata.get("user_id")
    from_uid = metadata.get("from_uid")
    if not all([shop_id, user_id, from_uid]):
        _logger.debug("未回复安抚跳过：缺少 shop/user/from_uid")
        return False

    notice = str(
        config.get("chat.unhandled_fallback_notice") or _default_notice()
    ).strip()
    if not notice:
        return False

    from Message.handlers.channel_send import send_text_to_buyer

    ok = await send_text_to_buyer(
        shop_id,
        user_id,
        from_uid,
        notice,
        context=context,
        metadata=metadata,
    )
    if ok:
        _logger.info(
            "已发送未处理消息安抚: buyer={} type={}",
            from_uid,
            context.type,
        )
    return ok
