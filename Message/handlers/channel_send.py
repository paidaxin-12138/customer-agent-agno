"""处理器链内统一的 MMS 文本发送（asyncio.to_thread，避免阻塞事件循环）。"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from bridge.context import Context
from utils.logger_loguru import get_logger

_logger = get_logger("ChannelSend")


def build_send_metadata(
    shop_id: Any,
    user_id: Any,
    from_uid: Any,
    *,
    channel_name: str = "pinduoduo",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if metadata:
        meta = dict(metadata)
        meta.setdefault("shop_id", str(shop_id))
        meta.setdefault("user_id", str(user_id))
        meta.setdefault("from_uid", str(from_uid))
        meta.setdefault("channel_name", channel_name)
        return meta
    return {
        "shop_id": str(shop_id),
        "user_id": str(user_id),
        "from_uid": str(from_uid),
        "channel_name": channel_name,
    }


async def send_text_to_buyer(
    shop_id: Any,
    user_id: Any,
    from_uid: Any,
    text: str,
    *,
    context: Optional[Context] = None,
    metadata: Optional[Dict[str, Any]] = None,
    notify_watchdog: bool = True,
) -> bool:
    """向买家发送文本；成功时可选通知 outbound watchdog。"""
    if not all([shop_id, user_id, from_uid]) or not str(text or "").strip():
        return False
    try:
        from Channel.pinduoduo.utils.API.send_message import SendMessage

        sender = SendMessage(str(shop_id), str(user_id))
        result = await asyncio.to_thread(
            sender.send_text, str(from_uid), str(text).strip()
        )
        if not (isinstance(result, dict) and result.get("success")):
            _logger.warning("send_text_to_buyer 失败: {}", result)
            return False
        if metadata is not None:
            metadata["_outbound_comfort_sent"] = True
        if notify_watchdog:
            try:
                from Message.handlers.ai_reply_watchdog import notify_outbound_reply

                meta = build_send_metadata(
                    shop_id, user_id, from_uid, metadata=metadata
                )
                notify_outbound_reply(context, meta)
            except Exception as e:
                _logger.debug("notify_outbound_reply: {}", e)
        return True
    except Exception as e:
        _logger.error("send_text_to_buyer 异常: {}", e)
        return False


def notify_outbound_from_metadata(
    context: Optional[Context] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """任意出站成功（含发卡等非文本）后通知 watchdog。"""
    try:
        from Message.handlers.ai_reply_watchdog import notify_outbound_reply

        notify_outbound_reply(context, metadata)
    except Exception as e:
        _logger.debug("notify_outbound_from_metadata: {}", e)


async def get_cs_list_async(shop_id: Any, user_id: Any) -> Optional[dict]:
    try:
        from Channel.pinduoduo.utils.API.send_message import SendMessage

        sender = SendMessage(str(shop_id), str(user_id))
        return await asyncio.to_thread(sender.getAssignCsList)
    except Exception as e:
        _logger.debug("get_cs_list_async: {}", e)
        return None


async def move_conversation_async(
    shop_id: Any, user_id: Any, from_uid: Any, cs_uid: str
) -> Optional[dict]:
    try:
        from Channel.pinduoduo.utils.API.send_message import SendMessage

        sender = SendMessage(str(shop_id), str(user_id))
        return await asyncio.to_thread(
            sender.move_conversation, str(from_uid), str(cs_uid)
        )
    except Exception as e:
        _logger.debug("move_conversation_async: {}", e)
        return None


async def transfer_to_available_cs_async(
    shop_id: Any,
    user_id: Any,
    from_uid: Any,
    *,
    exclude_self: bool = True,
) -> bool:
    """转接给第一个可用客服（默认排除当前账号）。"""
    cs_list = await get_cs_list_async(shop_id, user_id)
    if not cs_list or not isinstance(cs_list, dict):
        return False
    my_cs_uid = f"cs_{shop_id}_{user_id}"
    candidates = [
        uid for uid in cs_list.keys() if not exclude_self or uid != my_cs_uid
    ]
    if not candidates:
        return False
    result = await move_conversation_async(
        shop_id, user_id, from_uid, candidates[0]
    )
    return isinstance(result, dict) and bool(result.get("success"))
