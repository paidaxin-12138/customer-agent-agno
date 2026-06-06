"""WebSocket 连接建立后的心跳 + 消息循环会话。"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional, Set

from Channel.pinduoduo.ws_config import (
    HeartbeatConfig,
    connection_key,
    load_ws_message_concurrency,
)
from Channel.pinduoduo.ws_heartbeat import run_heartbeat_loop
from Channel.pinduoduo.ws_message_loop import run_message_loop
from core.connection_status import ConnectionStatusManager
from utils.logger_loguru import get_logger

_logger = get_logger("WSConnectSession")

MessageHandlerFn = Callable[[object], Awaitable[None]]
CleanupFn = Callable[[], Awaitable[None]]


def is_ws_closed(ws: Any) -> bool:
    try:
        closed = getattr(ws, "closed", None)
        if isinstance(closed, bool):
            return closed
        return False
    except Exception:
        return False


async def run_connected_session(
    websocket,
    *,
    shop_id: str,
    user_id: str,
    username: str,
    stop_event: asyncio.Event,
    heartbeat_config: HeartbeatConfig,
    heartbeat_tasks: Dict[str, asyncio.Task],
    processing_tasks: Set[asyncio.Task],
    status_manager: ConnectionStatusManager,
    on_message: MessageHandlerFn,
    on_cleanup: CleanupFn,
    logger=None,
) -> None:
    """
    连接成功后运行心跳与消息循环，直至 stop_event 或循环异常结束。
    结束时调用 on_cleanup（通常 keep_consumer=True）。
    """
    log = logger or _logger
    key = connection_key(shop_id, user_id)
    heartbeat_task: Optional[asyncio.Task] = None

    if heartbeat_config.enable_heartbeat:
        heartbeat_task = asyncio.create_task(
            run_heartbeat_loop(
                websocket,
                shop_id,
                user_id,
                username,
                stop_event,
                config=heartbeat_config,
                status_manager=status_manager,
                on_finished=lambda k: heartbeat_tasks.pop(k, None),
                logger=log,
            )
        )
        heartbeat_tasks[key] = heartbeat_task
        log.debug(f"心跳检查已启动: {shop_id}-{username}")

    message_task = asyncio.create_task(
        run_message_loop(
            websocket,
            shop_id=shop_id,
            user_id=user_id,
            username=username,
            stop_event=stop_event,
            on_message=on_message,
            processing_tasks=processing_tasks,
            max_inflight=load_ws_message_concurrency(),
            logger=log,
        )
    )

    stop_task = asyncio.create_task(stop_event.wait())
    try:
        tasks = [message_task, stop_task]
        if heartbeat_task:
            tasks.append(heartbeat_task)

        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        if stop_task in done:
            log.debug(f"收到停止信号: {shop_id}-{username}")
        else:
            log.warning(f"消息循环异常结束: {shop_id}-{username}")

        for task in pending:
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, asyncio.InvalidStateError):
                pass
            except Exception as exc:
                log.debug(f"等待任务取消时出错: {exc}")

        await on_cleanup()

    except asyncio.CancelledError:
        log.debug(f"WebSocket任务被取消: {shop_id}-{username}")
        message_task.cancel()
        if heartbeat_task:
            heartbeat_task.cancel()
        try:
            await asyncio.wait_for(message_task, timeout=3.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, asyncio.InvalidStateError):
            pass
        if heartbeat_task:
            try:
                await asyncio.wait_for(heartbeat_task, timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, asyncio.InvalidStateError):
                pass
        await on_cleanup()
        raise
