"""WebSocket 入站 JSON → PDDChatMessage → Context。"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from bridge.context import ChannelType, Context
from Channel.pinduoduo.pdd_message import PDDChatMessage
from database import db_manager
from utils.logger_loguru import get_logger

_logger = get_logger("WSContext")


def context_struct_payload(context: Context) -> Dict[str, Any]:
    """解析 Context.content；入队前 dict 会被 json.dumps 成字符串。"""
    raw = context.content
    if isinstance(raw, dict):
        return raw
    if not raw or not isinstance(raw, str):
        return {}
    text = raw.strip()
    if not text.startswith("{"):
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_ws_raw_message(message: str, *, logger=None):
    """解析 WS 文本帧为 PDDChatMessage；失败返回 None。"""
    log = logger or _logger
    if not message or not message.strip():
        log.debug("收到空消息，跳过处理")
        return None
    try:
        message_data = json.loads(message)
    except json.JSONDecodeError:
        log.error(f"JSON解析失败: {message[:200]}")
        return None
    msg_type = message_data.get("type") if isinstance(message_data, dict) else None
    log.debug(f"收到 WS 消息 type={msg_type}")
    try:
        return PDDChatMessage(message_data)
    except Exception as exc:
        log.error(f"创建PDD消息对象失败: {exc}")
        return None


def convert_pdd_message_to_context(
    pdd_message: PDDChatMessage,
    channel_name: str,
    shop_id: str,
    user_id: str,
    username: str,
    *,
    logger=None,
) -> Optional[Context]:
    """将 PDDChatMessage 转为 Context。"""
    log = logger or _logger
    try:
        shop_info = db_manager.get_shop(channel_name, shop_id)
        shop_name = shop_info.get("shop_name", "") if shop_info else ""

        content = pdd_message.content
        if isinstance(content, dict):
            content = json.dumps(content, ensure_ascii=False)
        elif content is None:
            content = ""
        else:
            content = str(content)

        return Context.create_pinduoduo_context(
            content=content,
            msg_id=str(pdd_message.msg_id) if pdd_message.msg_id is not None else "",
            from_user=str(pdd_message.from_user) if pdd_message.from_user is not None else "",
            from_uid=str(pdd_message.from_uid) if pdd_message.from_uid is not None else "",
            to_user=str(pdd_message.to_user) if pdd_message.to_user is not None else "",
            to_uid=str(pdd_message.to_uid) if pdd_message.to_uid is not None else "",
            nickname=str(pdd_message.nickname) if pdd_message.nickname is not None else "",
            timestamp=pdd_message.timestamp,
            user_msg_type=pdd_message.user_msg_type,
            shop_id=str(shop_id),
            user_id=str(user_id),
            username=str(username),
            shop_name=str(shop_name),
            raw_data=pdd_message.raw_data,
            channel_type=ChannelType.PINDUODUO,
        )
    except Exception as exc:
        log.error(f"转换消息格式时发生错误: {exc}")
        return None
