# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""WebSocket 立即处理消息（AUTH / 转接 / 快捷退款卡等，不入队）。"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from bridge.context import Context, ContextType
from Channel.pinduoduo.ws_auth_notify import notify_auth_success
from Channel.pinduoduo.ws_config import connection_key
from Channel.pinduoduo.ws_context import context_struct_payload
from config import config
from utils.logger_loguru import get_logger

_logger = get_logger("WSImmediate")


async def handle_immediate_message(
    context: Context,
    *,
    channel_name: str,
    shop_id: str,
    user_id: str,
    username: str,
    queue_name: str,
    ws_connections: Dict[str, Any],
    logger=None,
) -> None:
    """立即处理的消息类型（不进入 MessageConsumer 队列）。"""
    log = logger or _logger
    recipient_uid = context.kwargs.from_uid
    try:
        from Channel.pinduoduo.utils.API.send_message import SendMessage

        send_message = SendMessage(shop_id, user_id)
        if context.type == ContextType.AUTH:
            await _handle_auth(
                context,
                channel_name=channel_name,
                shop_id=shop_id,
                user_id=user_id,
                username=username,
                ws_connections=ws_connections,
                logger=log,
            )
        elif context.type == ContextType.WITHDRAW:
            log.info(f"收到撤回消息: {context.content}")
            await asyncio.to_thread(send_message.send_text, recipient_uid, "[玫瑰]")
        elif context.type == ContextType.SYSTEM_STATUS:
            log.debug(f"系统状态消息: {context.content}")
        elif context.type == ContextType.SYSTEM_HINT:
            log.info(f"系统提示: {context.content}")
        elif context.type == ContextType.MALL_CS:
            await handle_mall_cs_message(
                context, shop_id, user_id, send_message, logger=log
            )
        elif context.type == ContextType.SYSTEM_BIZ:
            log.info(f"系统业务消息: {context.content}")
        elif context.type == ContextType.MALL_SYSTEM_MSG:
            await handle_mall_system_msg(
                context, shop_id, user_id, send_message, logger=log
            )
        elif context.type == ContextType.TRANSFER:
            await handle_inbound_transfer(
                context,
                channel_name=channel_name,
                shop_id=shop_id,
                user_id=user_id,
                username=username,
                queue_name=queue_name,
                send_message=send_message,
                logger=log,
            )
    except Exception as e:
        log.error(f"立即处理消息失败: {e}")


async def _handle_auth(
    context: Context,
    *,
    channel_name: str,
    shop_id: str,
    user_id: str,
    username: str,
    ws_connections: Dict[str, Any],
    logger,
) -> None:
    auth_info = context_struct_payload(context)
    if not auth_info and isinstance(context.content, dict):
        auth_info = context.content
    result = auth_info.get("result")
    if result == "ok":
        logger.info(f"{username}认证成功")
        notify_auth_success(connection_key(shop_id, user_id))
        try:
            from core.ws_reconnect_reconcile import schedule_reconcile_after_auth

            schedule_reconcile_after_auth(
                channel_name=channel_name,
                shop_id=shop_id,
                user_id=user_id,
                username=username,
            )
        except Exception as exc:
            logger.debug("WS 重连补偿调度跳过: {}", exc)
        return
    logger.warning(f"{username} auth result: fail，关闭连接触发重连")
    from Channel.pinduoduo.ws_auth_notify import record_auth_failure
    from Channel.pinduoduo.ws_connection import safe_close_websocket

    key = connection_key(shop_id, user_id)
    record_auth_failure(key, username=username)
    ws = ws_connections.get(key)
    if ws:
        await safe_close_websocket(ws, logger=logger)


async def handle_inbound_transfer(
    context: Context,
    *,
    channel_name: str,
    shop_id: str,
    user_id: str,
    username: str,
    queue_name: str,
    send_message: Any,
    logger=None,
) -> None:
    """售前/其他客服转接进线：记录已在 hub 完成；可选强制接管并入队未回复。"""
    log = logger or _logger
    from utils.pdd_transfer import resolve_buyer_uid_from_transfer

    buyer_uid = resolve_buyer_uid_from_transfer(context)
    log.info(
        "[TRANSFER] shop={}-{} buyer={} queue={} content={!r}",
        shop_id,
        username,
        buyer_uid,
        queue_name,
        context.content,
    )
    if not buyer_uid:
        log.warning(
            "转接消息未能解析买家 UID（shop={} user={}），请核对 WS raw_data",
            shop_id,
            user_id,
        )
        return
    try:
        from utils.transfer_takeover import apply_inbound_transfer_takeover

        await apply_inbound_transfer_takeover(
            channel_name=channel_name,
            shop_id=str(shop_id),
            seller_user_id=str(user_id),
            login_username=str(username),
            buyer_uid=str(buyer_uid),
            queue_name=queue_name,
        )
    except Exception as takeover_err:
        log.warning(f"转接强制接管失败: {takeover_err}")
    notice = str(config.get("chat.inbound_transfer_buyer_notice") or "").strip()
    if notice:
        await asyncio.to_thread(send_message.send_text, str(buyer_uid), notice)
    if bool(config.get("chat.transfer_auto_rose_enabled", False)):
        await asyncio.to_thread(send_message.send_text, str(buyer_uid), "[玫瑰]")


async def notify_refund_card_unusable(
    shop_id: str,
    buyer_uid: str,
    send_message: Any,
    *,
    order_sn: Optional[str] = None,
    reason: str = "expired",
    logger=None,
) -> None:
    from utils.session_order_cache import get_recent_order, mark_refund_card_unusable

    uid = str(buyer_uid)
    sn = (order_sn or "").strip() or get_recent_order(str(shop_id), uid)
    if sn:
        mark_refund_card_unusable(str(shop_id), uid, sn)
    notice = config.get(
        "chat.after_sales_apply_merchant_window_expired_notice"
    ) or config.get(
        "chat.after_sales_apply_card_expired_notice",
        "亲，该订单商家代申请退款的时效已过或次数已满，快捷退款卡片无法使用。"
        "请您打开订单详情点击「申请售后」自行提交，或回复「人工」为您处理~",
    )
    if notice:
        await asyncio.to_thread(send_message.send_text, uid, str(notice))


async def handle_mall_cs_message(
    context: Context,
    shop_id: str,
    user_id: str,
    send_message: Any,
    *,
    logger=None,
) -> None:
    """本店客服消息；解析 type=19 快捷退款卡下行（含是否已过期）。"""
    log = logger or _logger
    from utils.platform_system_msg import is_platform_civility_message

    if is_platform_civility_message(context):
        log.info("忽略平台文明用语 mall_cs 消息: {!r}", context.content)
        return
    payload = context_struct_payload(context)
    if payload.get("event") != "ask_refund_card_push":
        if context.content:
            log.debug(f"收到客服消息: {context.content}")
        return

    from Channel.pinduoduo.utils.API.chat_orders import refund_card_push_expired

    buyer_uid = payload.get("to_uid")
    order_sn = payload.get("order_sn")
    expired = refund_card_push_expired(
        {"expire_text": payload.get("state_expire_text")},
        {
            "expire_text": payload.get("mstate_expire_text"),
            "status": payload.get("mstate_status"),
        },
    )
    mstate_status = payload.get("mstate_status")
    from utils.merchant_refund_apply_record import (
        RefundApplyGate,
        gate_notice,
        get_apply_counts,
        update_apply_from_card_push,
    )

    valid_time_unix: Optional[int] = None
    try:
        vt_raw = payload.get("valid_time")
        if vt_raw is not None:
            valid_time_unix = int(float(vt_raw))
    except (TypeError, ValueError):
        pass

    if buyer_uid and order_sn:
        update_apply_from_card_push(
            str(shop_id),
            str(buyer_uid),
            str(order_sn),
            card_msg_id=str(payload.get("card_msg_id") or "") or None,
            valid_time_unix=valid_time_unix,
            card_expired=expired,
        )
        counts = get_apply_counts(str(shop_id), str(buyer_uid), str(order_sn))
        log.info(
            f"代申请记录已更新 order_sn={order_sn} expired={expired} "
            f"valid_time={valid_time_unix} 本单成功={counts.get('order_total', 0)}"
        )

    log.info(
        f"快捷退款卡下行 order_sn={order_sn} buyer={buyer_uid} "
        f"state_expire={payload.get('state_expire_text')!r} "
        f"mstate_status={mstate_status} mstate_expire={payload.get('mstate_expire_text')!r} "
        f"valid_time={payload.get('valid_time')} expired={expired}"
    )
    if not buyer_uid:
        return
    if expired:
        log.warning(
            f"商家代申请退款窗口已失效 order_sn={order_sn} buyer={buyer_uid} "
            f"(mstate.status={payload.get('mstate_status')} 且 expire_text=已过期，"
            f"通常为同单重复代申请或超时)"
        )
        from utils.session_order_cache import mark_refund_card_unusable

        mark_refund_card_unusable(str(shop_id), str(buyer_uid), str(order_sn))
        notice = gate_notice(RefundApplyGate.EXPIRED_NOTICE)
        await asyncio.to_thread(send_message.send_text, str(buyer_uid), notice)
        return
    remain_h: Optional[float] = None
    try:
        vt = float(payload.get("valid_time") or 0)
        if vt > 0:
            remain_h = max(0.0, (vt - time.time()) / 3600.0)
    except (TypeError, ValueError):
        pass
    if remain_h is not None:
        log.info(
            f"快捷退款卡有效 order_sn={order_sn} "
            f"(mstate.status={mstate_status} 平台valid_time剩余={remain_h:.1f}h)"
        )
    else:
        log.info(
            f"快捷退款卡有效 order_sn={order_sn} "
            f"(mstate.status={mstate_status} 平台未下发 valid_time)"
        )
    follow = config.get("chat.after_sales_apply_follow_text") or ""
    if follow:
        await asyncio.to_thread(send_message.send_text, str(buyer_uid), str(follow))


async def handle_mall_system_msg(
    context: Context,
    shop_id: str,
    user_id: str,
    send_message: Any,
    *,
    logger=None,
) -> None:
    """商城系统消息：快捷退款卡过期/确认等平台侧通知。"""
    log = logger or _logger
    from utils.platform_system_msg import is_platform_civility_message

    if is_platform_civility_message(context):
        log.info("忽略平台文明用语 mall_system_msg: {!r}", context.content)
        return
    payload = context_struct_payload(context)
    event = payload.get("event")
    if event == "refund_card_confirmed":
        log.info(
            f"买家已确认快捷退款卡 shop={shop_id} buyer={payload.get('user_id')} "
            f"card_msg_id={payload.get('msg_id')}"
        )
        return
    if event != "refund_card_expired":
        if payload:
            from utils.log_redact import redact_log_payload

            log.debug(f"商城系统消息: {redact_log_payload(payload)}")
        return

    buyer_uid = payload.get("user_id")
    card_msg_id = payload.get("msg_id")
    log.warning(
        f"快捷退款卡已过期 shop={shop_id} buyer={buyer_uid} card_msg_id={card_msg_id}"
    )
    if not buyer_uid:
        return
    from database.db_manager import db_manager
    from utils.merchant_refund_apply_record import RefundApplyGate, gate_notice, mark_apply_expired

    row = (
        db_manager.get_refund_apply_by_card_msg_id(str(shop_id), str(card_msg_id))
        if card_msg_id
        else None
    )
    already_expired = row and (row.get("status") or "") == "expired"
    sn = (row or {}).get("order_sn") or ""
    if sn:
        mark_apply_expired(
            str(shop_id), sn, buyer_uid=str(buyer_uid), card_msg_id=card_msg_id
        )
    elif card_msg_id:
        mark_apply_expired(
            str(shop_id),
            "",
            buyer_uid=str(buyer_uid),
            card_msg_id=card_msg_id,
        )
    if already_expired:
        return
    notice = gate_notice(RefundApplyGate.EXPIRED_NOTICE)
    await asyncio.to_thread(send_message.send_text, str(buyer_uid), notice)
