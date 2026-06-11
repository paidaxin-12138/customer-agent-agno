# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""ws_config / ws_lifecycle / ws_connect_session 单测。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from Channel.pinduoduo.ws_config import build_pdd_ws_url, connection_key
from Channel.pinduoduo.ws_connect_session import is_ws_closed, run_connected_session
from Channel.pinduoduo.ws_lifecycle import cleanup_connection_resources, stop_all_connections
from core.connection_status import ConnectionStatusManager


def test_connection_key():
    assert connection_key("570414651", "184046586") == "570414651_184046586"


def test_build_pdd_ws_url():
    url = build_pdd_ws_url("tok123")
    assert url.startswith("wss://m-ws.pinduoduo.com/?")
    assert "access_token=tok123" in url
    assert "role=mall_cs" in url


def test_is_ws_closed():
    assert is_ws_closed(MagicMock(closed=True)) is True
    assert is_ws_closed(MagicMock(closed=False)) is False


@pytest.mark.asyncio
async def test_stop_all_connections_clears_registry():
    stop_event = asyncio.Event()
    stop_events = {"a_1": asyncio.Event()}
    reconnect = {"a_1": AsyncMock(done=MagicMock(return_value=False))}
    reconnect["a_1"].cancel = MagicMock()
    heartbeat = {}
    ws_connections = {"a_1": MagicMock()}

    with patch(
        "Channel.pinduoduo.ws_lifecycle.safe_close_websocket",
        new_callable=AsyncMock,
    ):
        await stop_all_connections(
            stop_event=stop_event,
            stop_events=stop_events,
            reconnect_tasks=reconnect,
            heartbeat_tasks=heartbeat,
            ws_connections=ws_connections,
        )

    assert stop_event.is_set()
    assert ws_connections == {}


@pytest.mark.asyncio
async def test_cleanup_keeps_consumer_when_requested():
    processing: set = set()
    reconnect: dict = {}
    heartbeat: dict = {}
    ws_connections = {"570414651_1": MagicMock()}
    stop_events = {"570414651_1": asyncio.Event()}

    with (
        patch(
            "Channel.pinduoduo.ws_lifecycle.cancel_task_set",
            new_callable=AsyncMock,
        ),
        patch(
            "Channel.pinduoduo.ws_lifecycle.cancel_tasks_in_registry",
            new_callable=AsyncMock,
        ),
        patch(
            "Channel.pinduoduo.ws_lifecycle.safe_close_websocket",
            new_callable=AsyncMock,
        ),
        patch("Message.message_consumer_manager.stop_consumer", new_callable=AsyncMock) as stop_consumer,
    ):
        await cleanup_connection_resources(
            queue_name="pdd_570414651",
            connection_key="570414651_1",
            keep_consumer=True,
            reconnect_tasks=reconnect,
            heartbeat_tasks=heartbeat,
            ws_connections=ws_connections,
            stop_events=stop_events,
            processing_tasks=processing,
            processing_task_payloads={},
            processing_task_queue_names={},
            resource_manager=MagicMock(),
        )

    stop_consumer.assert_not_awaited()
    assert "570414651_1" not in ws_connections


@pytest.mark.asyncio
async def test_run_connected_session_stops_on_event():
    stop_event = asyncio.Event()
    ws = MagicMock()
    ws.__aiter__ = MagicMock(return_value=iter([]))
    cleanup = AsyncMock()
    status = ConnectionStatusManager()

    with patch(
        "Channel.pinduoduo.ws_connect_session.run_message_loop",
        new_callable=AsyncMock,
    ) as msg_loop:
        stop_event.set()
        await run_connected_session(
            ws,
            shop_id="570414651",
            user_id="1",
            username="shop1",
            stop_event=stop_event,
            heartbeat_config=MagicMock(enable_heartbeat=False),
            heartbeat_tasks={},
            processing_tasks=set(),
            processing_task_payloads={},
            processing_task_queue_names={},
            status_manager=status,
            on_message=AsyncMock(),
            on_cleanup=cleanup,
        )

    cleanup.assert_awaited_once()
    msg_loop.assert_awaited_once()
