# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""WebSocket 消息接收循环（从 pdd_chnnel 抽离）。"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Dict, Optional, Set

from websockets import exceptions as ws_exceptions

from utils.logger_loguru import get_logger

_logger = get_logger("WSMessageLoop")

MessageHandlerFn = Callable[[object], Awaitable[None]]


async def _await_inflight_tasks(
    processing_tasks: Set[asyncio.Task],
    *,
    logger=None,
) -> None:
    log = logger or _logger
    pending = [t for t in list(processing_tasks) if not t.done()]
    if not pending:
        return
    log.debug("等待 {} 个在途 WS 消息处理完成", len(pending))
    await asyncio.gather(*pending, return_exceptions=True)


async def run_message_loop(
    websocket,
    *,
    shop_id: str,
    user_id: str,
    username: str,
    stop_event: asyncio.Event,
    on_message: MessageHandlerFn,
    processing_tasks: Set[asyncio.Task],
    task_payloads: Optional[Dict[asyncio.Task, object]] = None,
    task_queue_names: Optional[Dict[asyncio.Task, str]] = None,
    max_inflight: int = 32,
    logger=None,
) -> None:
    """从 WebSocket 读消息并并发 dispatch 到 on_message（有界并发）。"""
    log = logger or _logger
    sem = asyncio.Semaphore(max(4, min(max_inflight, 64)))
    payloads = task_payloads if task_payloads is not None else None
    queue_names = task_queue_names if task_queue_names is not None else None
    account_queue_name = ""
    try:
        from Channel.pinduoduo.ws_config import queue_name_for_account

        account_queue_name = queue_name_for_account(shop_id, user_id)
    except Exception:
        pass

    async def _dispatch_one(message: object) -> None:
        async with sem:
            await on_message(message)

    def _track_task(task: asyncio.Task, message: object) -> None:
        processing_tasks.add(task)

        def _done(t: asyncio.Task) -> None:
            processing_tasks.discard(t)
            if payloads is not None:
                payloads.pop(t, None)
            if queue_names is not None:
                queue_names.pop(t, None)

        task.add_done_callback(_done)
        if payloads is not None:
            payloads[task] = message
        if queue_names is not None and account_queue_name:
            queue_names[task] = account_queue_name

    try:
        log.info(f"消息循环开始: {shop_id}-{username}")

        async for message in websocket:
            if stop_event.is_set():
                log.info(f"停止事件已设置，退出消息循环: {shop_id}-{username}")
                break
            task = asyncio.create_task(_dispatch_one(message))
            _track_task(task, message)

    except ws_exceptions.ConnectionClosed as cc:
        log.warning(
            f"WebSocket连接正常关闭: {shop_id}-{username}, 代码: {cc.code}"
        )
    except ws_exceptions.ConnectionClosedError as cce:
        log.error(f"WebSocket连接异常关闭: {shop_id}-{username}, 错误: {cce}")
    except Exception as e:
        log.error(f"消息循环错误: {shop_id}-{username}, 错误: {e}")
    finally:
        await _await_inflight_tasks(processing_tasks, logger=log)
