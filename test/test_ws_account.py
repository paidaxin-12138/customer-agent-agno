# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""ws_account 单账号启停与会话。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from Channel.pinduoduo.ws_account import (
    PDDChannelRuntime,
    launch_account_connect,
    resolve_pdd_account,
    run_account_ws_connect,
    runtime_from_channel,
)
from Channel.pinduoduo.ws_config import HeartbeatConfig, ReconnectConfig
from core.connection_status import ConnectionState, ConnectionStatusManager


def _runtime(**overrides) -> PDDChannelRuntime:
    ch = MagicMock()
    ch.channel_name = "pinduoduo"
    ch.logger = MagicMock()
    ch.status_manager = ConnectionStatusManager()
    ch.reconnect_config = ReconnectConfig(enable_auto_reconnect=False)
    ch.heartbeat_config = HeartbeatConfig()
    ch._stop_events = {}
    ch._reconnect_tasks = {}
    ch._heartbeat_tasks = {}
    ch._ws_connections = {}
    ch.processing_tasks = set()
    ch.processing_task_payloads = {}
    ch.processing_task_queue_names = {}
    ch.resource_manager = MagicMock()
    ch.businessHours = None
    ch.message_semaphore = asyncio.Semaphore(4)
    ch._cleanup_resources = AsyncMock()
    ch.ws = None
    ch._stop_event = None
    for k, v in overrides.items():
        setattr(ch, k, v)
    return runtime_from_channel(ch)


def test_resolve_pdd_account_missing():
    with patch("database.db_manager.db_manager.get_account", return_value=None):
        username, row = resolve_pdd_account("pinduoduo", "s", "u")
    assert username is None and row is None


@pytest.mark.asyncio
async def test_launch_account_connect_without_reconnect():
    rt = _runtime()
    attempt = AsyncMock()

    await launch_account_connect(
        "shop1",
        "u1",
        "user1",
        runtime=rt,
        connect_attempt=attempt,
        on_success=MagicMock(),
        on_failure=MagicMock(),
    )

    assert "shop1_u1" in rt.reconnect_tasks
    await asyncio.sleep(0)
    attempt.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_account_ws_connect_success_path():
    rt = _runtime()
    ch = rt._channel
    on_success = MagicMock()
    on_inbound = AsyncMock()
    mock_ws = MagicMock(closed=False)

    with (
        patch(
            "Channel.pinduoduo.ws_account.GetToken",
            return_value=MagicMock(get_token=MagicMock(return_value="tok")),
        ),
        patch(
            "Channel.pinduoduo.ws_account.setup_message_consumer",
            new_callable=AsyncMock,
        ),
        patch(
            "Channel.pinduoduo.ws_account.connect_pdd_ws",
        ) as connect_cm,
        patch(
            "Channel.pinduoduo.ws_account.set_account_online",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "Channel.pinduoduo.ws_account.run_connected_session",
            new_callable=AsyncMock,
        ),
        patch(
            "Channel.pinduoduo.ws_account.is_ws_closed",
            return_value=False,
        ),
    ):
        connect_cm.return_value.__aenter__ = AsyncMock(return_value=mock_ws)
        connect_cm.return_value.__aexit__ = AsyncMock(return_value=None)

        await run_account_ws_connect(
            "shop1",
            "u1",
            "user1",
            runtime=rt,
            on_success=on_success,
            on_failure=MagicMock(),
            on_inbound=on_inbound,
        )

    on_success.assert_not_called()
    assert ch.ws is mock_ws
    st = ch.status_manager.get_status("shop1", "u1")
    assert st is not None
    assert st.state == ConnectionState.CONNECTED
