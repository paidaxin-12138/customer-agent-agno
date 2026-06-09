# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""WebSocket 消息循环单测。"""
from __future__ import annotations

import asyncio
from typing import List

import pytest

from Channel.pinduoduo.ws_message_loop import run_message_loop


class _FakeWebSocket:
    def __init__(self, messages: List[str]):
        self._messages = list(messages)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)


@pytest.mark.asyncio
async def test_message_loop_dispatches_each_message():
    received: List[str] = []
    stop = asyncio.Event()
    tasks: set = set()

    async def _on_message(msg):
        received.append(str(msg))

    ws = _FakeWebSocket(["a", "b"])
    await run_message_loop(
        ws,
        shop_id="s",
        user_id="u",
        username="cs",
        stop_event=stop,
        on_message=_on_message,
        processing_tasks=tasks,
    )
    await asyncio.sleep(0.05)

    assert received == ["a", "b"]


@pytest.mark.asyncio
async def test_message_loop_exits_immediately_when_stopped():
    received: list[str] = []
    stop = asyncio.Event()
    stop.set()

    async def _on_message(msg):
        received.append(str(msg))

    tasks: set = set()
    await run_message_loop(
        _FakeWebSocket(["ignored"]),
        shop_id="s",
        user_id="u",
        username="cs",
        stop_event=stop,
        on_message=_on_message,
        processing_tasks=tasks,
    )
    await asyncio.sleep(0.05)

    assert received == []
