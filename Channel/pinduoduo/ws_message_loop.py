# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""WebSocket 消息接收循环（从 pdd_chnnel 抽离）。"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Set

from websockets import exceptions as ws_exceptions

from utils.logger_loguru import get_logger

_logger = get_logger("WSMessageLoop")

MessageHandlerFn = Callable[[object], Awaitable[None]]


async def run_message_loop(
    websocket,
    *,
    shop_id: str,
    user_id: str,
    username: str,
    stop_event: asyncio.Event,
    on_message: MessageHandlerFn,
    processing_tasks: Set[asyncio.Task],
    max_inflight: int = 32,
    logger=None,
) -> None:
    """从 WebSocket 读消息并并发 dispatch 到 on_message（有界并发）。"""
    log = logger or _logger
    sem = asyncio.Semaphore(max(4, min(max_inflight, 64)))

    async def _dispatch_one(message: object) -> None:
        async with sem:
            await on_message(message)

    try:
        log.info(f"消息循环开始: {shop_id}-{username}")

        async for message in websocket:
            if stop_event.is_set():
                log.info(f"停止事件已设置，退出消息循环: {shop_id}-{username}")
                break
            task = asyncio.create_task(_dispatch_one(message))
            processing_tasks.add(task)
            task.add_done_callback(processing_tasks.discard)

    except ws_exceptions.ConnectionClosed as cc:
        log.warning(
            f"WebSocket连接正常关闭: {shop_id}-{username}, 代码: {cc.code}"
        )
    except ws_exceptions.ConnectionClosedError as cce:
        log.error(f"WebSocket连接异常关闭: {shop_id}-{username}, 错误: {cce}")
    except Exception as e:
        log.error(f"消息循环错误: {shop_id}-{username}, 错误: {e}")
