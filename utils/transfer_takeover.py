# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
转接进线后的强制接管：重置 stage、可选切 AI、将本地未回复买家消息重新入队处理。

说明：
- 拼多多转接推送本身不入业务队列；转接前聊天记录需已写入本地 DB（WS 曾收到或后续买家新消息）。
- MMS 历史拉取接口尚未接通（见 get_messages.py），无法在转接瞬间从平台补拉全量历史。
"""

from __future__ import annotations

import time
from typing import Any, List, Optional

from bridge.context import ChannelType, Context, ContextType
from config import config
from utils.logger_loguru import get_logger

logger = get_logger("TransferTakeover")


def _transfer_stage() -> str:
    from core.session_stages import VALID_SESSION_STAGES

    raw = str(config.get("chat.inbound_transfer_stage", "after_sales") or "after_sales").strip()
    if raw not in VALID_SESSION_STAGES:
        return "after_sales"
    return raw


def _takeover_enabled() -> bool:
    return bool(config.get("chat.inbound_transfer_force_takeover", True))


def _takeover_ai_mode() -> bool:
    """转接后是否强制 AI 接待（覆盖 inbound_transfer_default_manual）。"""
    if not _takeover_enabled():
        return not bool(config.get("chat.inbound_transfer_default_manual", True))
    explicit = config.get("chat.inbound_transfer_takeover_ai_mode")
    if explicit is not None:
        return bool(explicit)
    return True


def _enqueue_unreplied_enabled() -> bool:
    return bool(config.get("chat.inbound_transfer_enqueue_unreplied", True))


def inbound_transfer_initial_ai_mode() -> bool:
    """
    转接入库时会话初始 ai_mode。
    开启强制接管且 takeover_ai_mode 时为 True，否则沿用 inbound_transfer_default_manual。
    """
    if _takeover_enabled() and _takeover_ai_mode():
        return True
    return not bool(config.get("chat.inbound_transfer_default_manual", True))


def _resolve_session_id(
    channel_name: str,
    shop_id: str,
    seller_user_id: str,
    buyer_uid: str,
) -> Optional[int]:
    from database.session_store import resolve_session_id

    return resolve_session_id(
        channel_name=channel_name,
        shop_id=shop_id,
        seller_user_id=seller_user_id,
        buyer_uid=buyer_uid,
        allow_any_status=True,
    )


def _build_synthetic_context(
    *,
    text: str,
    buyer_uid: str,
    shop_id: str,
    seller_user_id: str,
    username: str,
    channel_name: str = "pinduoduo",
) -> Context:
    ts_ms = int(time.time() * 1000)
    return Context.create_pinduoduo_context(
        content=text,
        msg_id=f"transfer_takeover_{ts_ms}",
        from_user="user",
        from_uid=str(buyer_uid),
        to_user="mall_cs",
        to_uid=str(seller_user_id),
        nickname="买家",
        timestamp=str(ts_ms),
        user_msg_type=ContextType.TEXT,
        shop_id=str(shop_id),
        user_id=str(seller_user_id),
        username=str(username),
        raw_data={"_transfer_takeover": True, "_session_stage": _transfer_stage()},
        channel_type=ChannelType.PINDUODUO,
    )


async def apply_inbound_transfer_takeover(
    *,
    channel_name: str,
    shop_id: str,
    seller_user_id: str,
    login_username: str,
    buyer_uid: str,
    queue_name: str,
) -> bool:
    """
    转接后截流接管：stage→idle、可选 ai_mode=True、未回复买家消息重新入队走责任链。
    返回是否执行了入队（有未回复 backlog 时 True）。
    """
    if not _takeover_enabled():
        return False
    buyer_uid = str(buyer_uid or "").strip()
    if not buyer_uid:
        return False

    sid = _resolve_session_id(channel_name, shop_id, seller_user_id, buyer_uid)
    if sid is None:
        logger.warning(
            "转接接管跳过：无会话记录 buyer={} shop={} seller={}",
            buyer_uid,
            shop_id,
            seller_user_id,
        )
        return False

    try:
        from utils.inbound_transfer_gate import mark_inbound_transferred

        mark_inbound_transferred(sid)
    except Exception as e:
        logger.debug("转接接管标记 inbound_transferred: {}", e)

    try:
        from Agent.CustomerAgent.conversation_memory import update_session_state
        from database.db_manager import db_manager

        update_session_state(
            sid,
            stage=_transfer_stage(),
            intent="after_sales",
            clear_flow_state=True,
            source_handler="InboundTransferTakeover",
        )
        if _takeover_ai_mode():
            from database.session_store import set_ai_mode

            set_ai_mode(sid, True)
            logger.info(
                "转接接管: session={} buyer={} stage={} ai_mode=True",
                sid,
                buyer_uid,
                _transfer_stage(),
            )
        else:
            logger.info(
                "转接接管: session={} buyer={} stage={} ai_mode=unchanged(manual)",
                sid,
                buyer_uid,
                _transfer_stage(),
            )
    except Exception as e:
        logger.warning("转接接管写会话状态失败: {}", e)

    if not _enqueue_unreplied_enabled():
        return False

    try:
        from utils.unreplied_buyer_messages import get_unreplied_buyer_messages

        max_parts = int(config.get("chat.unreplied_buyer_max_parts", 3) or 3)
        parts: List[str] = get_unreplied_buyer_messages(sid, max_count=max_parts)
    except Exception as e:
        logger.debug("转接接管读取未回复失败: {}", e)
        parts = []

    if not parts:
        logger.debug("转接接管: 无本地未回复 backlog，等待 WS 新消息 buyer={}", buyer_uid)
        return False

    text = parts[-1] if len(parts) == 1 else "\n".join(parts)
    ctx = _build_synthetic_context(
        text=text,
        buyer_uid=buyer_uid,
        shop_id=shop_id,
        seller_user_id=seller_user_id,
        username=login_username,
        channel_name=channel_name,
    )
    try:
        from Message import put_message

        msg_id = await put_message(queue_name, ctx)
        logger.info(
            "转接接管已入队未回复处理: buyer={} queue={} parts={} msg_id={}",
            buyer_uid,
            queue_name,
            len(parts),
            msg_id,
        )
        return True
    except Exception as e:
        logger.warning("转接接管入队失败: {}", e)
        return False
