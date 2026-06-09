# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""WebSocket 任务清理单测。"""
from __future__ import annotations

import asyncio

import pytest

from Channel.pinduoduo.ws_task_cleanup import cancel_task_set, cancel_tasks_in_registry


@pytest.mark.asyncio
async def test_cancel_task_set_clears_running_tasks():
    tasks: set[asyncio.Task] = set()
    started = asyncio.Event()

    async def _worker():
        started.set()
        await asyncio.sleep(10)

    tasks.add(asyncio.create_task(_worker()))
    await started.wait()
    await cancel_task_set(tasks)
    assert len(tasks) == 0


@pytest.mark.asyncio
async def test_cancel_tasks_in_registry_single_key():
    registry: dict[str, asyncio.Task] = {}
    done = asyncio.Event()

    async def _worker():
        done.set()
        await asyncio.sleep(10)

    registry["a"] = asyncio.create_task(_worker())
    registry["b"] = asyncio.create_task(asyncio.sleep(10))
    await done.wait()

    await cancel_tasks_in_registry(registry, connection_key="a", cancel_timeout=1.0)

    assert "a" not in registry
    assert "b" in registry
    registry["b"].cancel()
    try:
        await registry["b"]
    except asyncio.CancelledError:
        pass
