# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""WebSocket 入站：预处理（Hub/文明用语/买家离开）与路由分发。"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional

from bridge.context import Context
from Channel.pinduoduo.pdd_message import PDDChatMessage
from Channel.pinduoduo.ws_context import (
    convert_pdd_message_to_context,
    parse_ws_raw_message,
)
from Channel.pinduoduo.ws_immediate_handlers import handle_immediate_message
from Channel.pinduoduo.ws_inbound_routing import InboundRoute, classify_inbound_route
from utils.logger_loguru import get_logger

_logger = get_logger("WSInbound")


def preprocess_inbound_context(
    context: Context,
    *,
    channel_name: str,
    shop_id: str,
    user_id: str,
    username: str,
    logger=None,
) -> None:
    """文明用语标记、买家离开检测、Hub 登记（best-effort，不阻断入队）。"""
    log = logger or _logger
    from utils.platform_system_msg import (
        is_platform_civility_message,
        mark_platform_civility_context,
    )

    if is_platform_civility_message(context):
        mark_platform_civility_context(context)
        from utils.log_redact import redact_log_payload

        log.info(
            "平台文明用语系统消息，不标记会话已回复: type={} content={!r}",
            context.type,
            redact_log_payload(str(context.content or "")),
        )

    from utils.best_effort import run_best_effort

    def _emit_buyer_left() -> None:
        from core.human_assist_bus import (
            emit_buyer_conversation_ended,
            text_suggests_buyer_left,
        )
        from ui.conversation_hub import parse_peer_from_context

        if text_suggests_buyer_left(context):
            buid, _ = parse_peer_from_context(context)
            if buid:
                emit_buyer_conversation_ended(
                    channel_name,
                    str(shop_id),
                    str(user_id),
                    str(username),
                    str(buid),
                )

    run_best_effort("买家离开检测", _emit_buyer_left, logger=log)

    def _record_hub() -> None:
        from core.conversation_record import (
            record_inbound_from_context,
            record_platform_civility_from_context,
        )

        if is_platform_civility_message(context):
            record_platform_civility_from_context(
                channel_name, shop_id, user_id, username, context
            )
        else:
            record_inbound_from_context(
                channel_name, shop_id, user_id, username, context
            )

    run_best_effort("Hub 会话登记", _record_hub, logger=log)


def log_transfer_buyer_mismatch(
    context: Context,
    *,
    user_id: str,
    logger=None,
) -> None:
    """转接后买家消息 to_uid 与当前 seller 不一致时的诊断日志。"""
    log = logger or _logger
    to_uid = str(getattr(context.kwargs, "to_uid", "") or "")
    from_user = str(getattr(context.kwargs, "from_user", "") or "")
    if from_user == "user" and to_uid and to_uid != str(user_id):
        log.info(
            "[TRANSFER/BUYER] 买家消息 to_uid={} 与当前登录 seller_uid={} 不一致（转接后常见），仍入队处理",
            to_uid,
            user_id,
        )


async def dispatch_inbound_message(
    context: Context,
    pdd_message: PDDChatMessage,
    *,
    channel_name: str,
    shop_id: str,
    user_id: str,
    username: str,
    queue_name: str,
    ws_connections: Dict[str, Any],
    put_message: Callable[[str, Context], Awaitable[Any]],
    logger=None,
) -> None:
    """按入站路由立即处理或入队。"""
    log = logger or _logger
    route = classify_inbound_route(context)
    from_uid = str(getattr(context.kwargs, "from_uid", "") or "")
    to_uid = str(getattr(context.kwargs, "to_uid", "") or "")
    msg_type = (
        pdd_message.raw_data.get("type")
        if isinstance(pdd_message.raw_data, dict)
        else None
    )

    if route == InboundRoute.IMMEDIATE:
        await handle_immediate_message(
            context,
            channel_name=channel_name,
            shop_id=shop_id,
            user_id=user_id,
            username=username,
            queue_name=queue_name,
            ws_connections=ws_connections,
            logger=log,
        )
        log.debug(
            f"立即处理消息: {context.type}, ID: {pdd_message.msg_id}"
        )
        return

    if route in (InboundRoute.QUEUE, InboundRoute.FORCE_QUEUE):
        tag = "[ENQUEUE/FORCE]" if route == InboundRoute.FORCE_QUEUE else "[ENQUEUE]"
        log.info(
            "{} queue={} msg_id={} type={} from_uid={} to_uid={}",
            tag,
            queue_name,
            pdd_message.msg_id,
            context.type,
            from_uid,
            to_uid,
        )
        if route == InboundRoute.FORCE_QUEUE:
            log.info("买家未知类型仍入队 ws_type={}", msg_type)
        try:
            wrapper_id = await put_message(queue_name, context)
        except RuntimeError as qerr:
            if "Queue is full" in str(qerr):
                log.error(
                    "{} 队列已满，消息丢弃 queue={} msg_id={} from_uid={}",
                    tag,
                    queue_name,
                    pdd_message.msg_id,
                    from_uid,
                )
                return
            raise
        if not wrapper_id:
            log.info(
                "{} 去重跳过 queue={} platform_msg_id={} from_uid={}",
                tag,
                queue_name,
                pdd_message.msg_id,
                from_uid,
            )
            return
        log.info(
            "{} 已入队 queue={} msg_id={} wrapper_id={}",
            tag,
            queue_name,
            pdd_message.msg_id,
            wrapper_id,
        )
        return

    log.debug(f"忽略消息: {context.type}, ID: {pdd_message.msg_id}")


async def process_inbound_ws_frame(
    message: str,
    *,
    channel_name: str,
    shop_id: str,
    user_id: str,
    username: str,
    queue_name: str,
    ws_connections: Dict[str, Any],
    put_message: Callable[[str, Context], Awaitable[Any]],
    logger=None,
) -> None:
    """解析单条 WS 帧 → 预处理 → 路由分发。"""
    log = logger or _logger
    try:
        pdd_message = parse_ws_raw_message(message, logger=log)
        if not pdd_message:
            return

        context = convert_pdd_message_to_context(
            pdd_message,
            channel_name,
            shop_id,
            user_id,
            username,
            logger=log,
        )
        if not context:
            log.debug(f"消息转换失败，跳过处理: {shop_id}-{username}")
            return

        await asyncio.to_thread(
            preprocess_inbound_context,
            context,
            channel_name=channel_name,
            shop_id=shop_id,
            user_id=user_id,
            username=username,
            logger=log,
        )
        log_transfer_buyer_mismatch(context, user_id=user_id, logger=log)

        await dispatch_inbound_message(
            context,
            pdd_message,
            channel_name=channel_name,
            shop_id=shop_id,
            user_id=user_id,
            username=username,
            queue_name=queue_name,
            ws_connections=ws_connections,
            put_message=put_message,
            logger=log,
        )
    except Exception as exc:
        log.error(f"处理WebSocket消息失败: {exc}")


async def run_inbound_ws_message_with_limit(
    message: str,
    *,
    semaphore: asyncio.Semaphore,
    channel_name: str,
    shop_id: str,
    user_id: str,
    username: str,
    queue_name: str,
    ws_connections: Dict[str, Any],
    put_message: Callable[[str, Context], Awaitable[Any]],
    logger=None,
) -> None:
    """带并发上限的单条 WS 消息处理（供 message_loop on_message 回调）。"""
    log = logger or _logger
    async with semaphore:
        try:
            await process_inbound_ws_frame(
                message,
                channel_name=channel_name,
                shop_id=shop_id,
                user_id=user_id,
                username=username,
                queue_name=queue_name,
                ws_connections=ws_connections,
                put_message=put_message,
                logger=log,
            )
        except Exception as exc:
            log.error(f"并发处理消息失败: {exc}")


async def run_inbound_for_channel(
    channel: Any,
    message: str,
    shop_id: str,
    user_id: str,
    username: str,
    queue_name: str,
) -> None:
    """PDDChannel 入站消息入口（封装 put_message + semaphore）。"""
    from Message import put_message

    await run_inbound_ws_message_with_limit(
        message,
        semaphore=channel.message_semaphore,
        channel_name=channel.channel_name,
        shop_id=shop_id,
        user_id=user_id,
        username=username,
        queue_name=queue_name,
        ws_connections=channel._ws_connections,
        put_message=put_message,
        logger=channel.logger,
    )

