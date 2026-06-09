# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""WebSocket 连接生命周期：单账号停止、资源清理、全部停止。"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional, Set

from Channel.pinduoduo.ws_config import connection_key
from Channel.pinduoduo.ws_connection import safe_close_websocket
from Channel.pinduoduo.ws_task_cleanup import cancel_task_set, cancel_tasks_in_registry
from core.connection_status import ConnectionState, ConnectionStatusManager
from utils.logger_loguru import get_logger

_logger = get_logger("WSLifecycle")


async def stop_single_account(
    shop_id: str,
    user_id: str,
    username: str,
    *,
    status_manager: ConnectionStatusManager,
    stop_events: Dict[str, asyncio.Event],
    cleanup_resources: Callable[..., Awaitable[None]],
    queue_name: str,
    logger=None,
) -> None:
    """停止单账号：触发 stop_event → 更新状态 → 统一资源清理。"""
    log = logger or _logger
    key = connection_key(shop_id, user_id)
    log.info(f"正在停止店铺 {shop_id} 账号 {username}")

    stop_event = stop_events.get(key)
    if stop_event:
        stop_event.set()

    status_manager.update_status(
        shop_id, user_id, username, ConnectionState.DISCONNECTED
    )

    await cleanup_resources(queue_name, connection_key=key)
    log.info(f"成功停止店铺 {shop_id} 账号 {username}")


async def cleanup_connection_resources(
    *,
    queue_name: str,
    connection_key: Optional[str],
    keep_consumer: bool,
    reconnect_tasks: Dict[str, asyncio.Task],
    heartbeat_tasks: Dict[str, asyncio.Task],
    ws_connections: Dict[str, Any],
    stop_events: Dict[str, asyncio.Event],
    processing_tasks: Set[asyncio.Task],
    resource_manager: Any,
    logger=None,
) -> None:
    """清理处理任务、连接任务、WebSocket 引用与消费者（按账号或全量）。"""
    log = logger or _logger
    from Message import message_consumer_manager

    try:
        await cancel_task_set(processing_tasks, logger=log)
        # 重连场景保留 reconnect_tasks，避免取消正在执行的 connect_with_retry
        if not keep_consumer:
            await cancel_tasks_in_registry(
                reconnect_tasks,
                connection_key=connection_key,
                cancel_timeout=5.0,
                logger=log,
            )
        await cancel_tasks_in_registry(
            heartbeat_tasks, connection_key=connection_key, cancel_timeout=3.0, logger=log
        )

        if connection_key:
            ws = ws_connections.pop(connection_key, None)
            if ws:
                await safe_close_websocket(ws, logger=log)
            stop_events.pop(connection_key, None)
        else:
            await resource_manager.cleanup_all()
            ws_connections.clear()
            stop_events.clear()

        # 每账号独立队列：仅在本连接断开且非重连保活时停止对应消费者
        should_stop_consumer = not keep_consumer
        if should_stop_consumer:
            try:
                await message_consumer_manager.stop_consumer(queue_name)
                log.debug(f"已停止消息消费者: {queue_name}")
            except asyncio.InvalidStateError:
                log.debug(f"消息消费者已在其他事件循环中停止: {queue_name}")
            except Exception as exc:
                log.warning(f"停止消息消费者失败: {queue_name}, {exc}")

    except Exception as exc:
        log.error(f"清理资源失败: {exc}")


async def stop_all_connections(
    *,
    stop_event: Optional[asyncio.Event],
    stop_events: Dict[str, asyncio.Event],
    reconnect_tasks: Dict[str, asyncio.Task],
    heartbeat_tasks: Dict[str, asyncio.Task],
    ws_connections: Dict[str, Any],
    logger=None,
) -> None:
    """停止所有连接并清理任务（不停止 message consumer，由应用关闭处理）。"""
    log = logger or _logger
    try:
        log.info("正在停止所有连接...")
        if stop_event:
            stop_event.set()
        for event in stop_events.values():
            event.set()

        for key, task in list(reconnect_tasks.items()):
            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    log.debug(f"任务已取消或超时: {key}")
                except Exception as exc:
                    log.error(f"停止任务时出错: {key}, {exc}")
            reconnect_tasks.pop(key, None)

        for key, task in list(heartbeat_tasks.items()):
            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=3.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    log.debug(f"心跳任务已取消或超时: {key}")
                except Exception as exc:
                    log.error(f"停止心跳任务时出错: {key}, {exc}")
            heartbeat_tasks.pop(key, None)

        for key, ws in list(ws_connections.items()):
            try:
                await safe_close_websocket(ws, logger=log)
            except Exception as exc:
                log.error(f"关闭连接失败: {key}, {exc}")
        ws_connections.clear()
        log.info("所有连接已停止")
    except Exception as exc:
        log.error(f"停止所有连接时发生错误: {exc}")
