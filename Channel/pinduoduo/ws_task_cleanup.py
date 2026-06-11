# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""WebSocket 异步任务清理（从 pdd_chnnel 抽离）。"""
from __future__ import annotations

import asyncio
from typing import Dict, Optional, Set

from utils.logger_loguru import get_logger

_logger = get_logger("WSTaskCleanup")


async def cancel_task_set(
    tasks: Set[asyncio.Task],
    *,
    logger=None,
    drain_wait_sec: float = 3.0,
    task_payloads: Optional[Dict[asyncio.Task, object]] = None,
    queue_name: str = "",
    task_queue_names: Optional[Dict[asyncio.Task, str]] = None,
) -> None:
    """等待在途任务自然完成后再取消剩余任务；可选将 WS 帧写入 dead-letter。"""
    log = logger or _logger
    if not tasks:
        return
    payloads = task_payloads or {}
    per_task_queues = task_queue_names or {}
    pending = [t for t in list(tasks) if not t.done()]
    if pending and drain_wait_sec > 0:
        log.debug("等待 {} 个在途 WS 任务完成（最多 {}s）", len(pending), drain_wait_sec)
        _done, still_pending = await asyncio.wait(
            pending,
            timeout=drain_wait_sec,
            return_when=asyncio.ALL_COMPLETED,
        )
        pending = list(still_pending)
    if pending:
        log.info(f"清理 {len(pending)} 个处理任务")
    for task in pending:
        raw = payloads.get(task)
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.error(f"清理任务失败: {e}")
        qn = per_task_queues.get(task) or queue_name
        if raw is not None and qn:
            try:
                from Message.dead_letter import persist_ws_frame_dead_letter

                persist_ws_frame_dead_letter(qn, raw)
            except Exception as exc:
                log.debug("WS frame dead-letter 跳过: {}", exc)
    tasks.clear()
    if payloads is not None:
        payloads.clear()
    if task_queue_names is not None:
        task_queue_names.clear()


async def cancel_tasks_in_registry(
    registry: Dict[str, asyncio.Task],
    *,
    connection_key: Optional[str] = None,
    cancel_timeout: float = 5.0,
    logger=None,
) -> None:
    """取消 registry 中指定或全部连接任务。"""
    log = logger or _logger
    try:
        keys = [connection_key] if connection_key else list(registry.keys())
        for key in keys:
            task = registry.get(key)
            if task is None:
                continue
            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=cancel_timeout)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
                except asyncio.InvalidStateError:
                    log.debug(f"任务在不同的的事件循环中: {key}")
                except Exception as e:
                    log.error(f"清理任务失败: {key}, {e}")
            registry.pop(key, None)
    except Exception as e:
        log.error(f"清理任务列表失败: {e}")
