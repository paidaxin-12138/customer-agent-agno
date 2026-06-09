# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""WebSocket 异步任务清理（从 pdd_chnnel 抽离）。"""
from __future__ import annotations

import asyncio
from typing import Dict, Optional, Set

from utils.logger_loguru import get_logger

_logger = get_logger("WSTaskCleanup")


async def cancel_task_set(tasks: Set[asyncio.Task], *, logger=None) -> None:
    """取消并等待一组在途任务完成。"""
    log = logger or _logger
    if not tasks:
        return
    log.info(f"清理 {len(tasks)} 个处理任务")
    for task in list(tasks):
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.error(f"清理任务失败: {e}")
    tasks.clear()


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
