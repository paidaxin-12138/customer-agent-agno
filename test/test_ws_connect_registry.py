"""ws_connect / pdd_channel_registry / heartbeat_status_all 单测。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from Channel.pinduoduo.ws_config import build_pdd_ws_url
from Channel.pinduoduo.ws_connect import WS_CLIENT_KWARGS, connect_pdd_ws
from core.channel_facade import heartbeat_status_all
from core.connection_status import ConnectionState, ConnectionStatusManager
from core.pdd_channel_registry import (
    build_heartbeat_status,
    live_heartbeat_keys,
    register_pdd_channel,
)


def test_ws_client_kwargs_ping_interval():
    assert WS_CLIENT_KWARGS["ping_interval"] == 60


@pytest.mark.asyncio
async def test_connect_pdd_ws_uses_build_url():
    mock_ws = MagicMock()
    cm = AsyncMock()
    cm.__aenter__.return_value = mock_ws
    cm.__aexit__.return_value = None

    with patch(
        "Channel.pinduoduo.ws_connect.websockets.connect",
        return_value=cm,
    ) as connect_mock:
        async with connect_pdd_ws("token-abc") as ws:
            assert ws is mock_ws

    connect_mock.assert_called_once()
    assert connect_mock.call_args[0][0] == build_pdd_ws_url("token-abc")


def test_live_heartbeat_keys_from_registered_channel():
    ch = MagicMock()
    task = MagicMock(done=MagicMock(return_value=False))
    ch._heartbeat_tasks = {"shop1_user1": task}
    register_pdd_channel(ch)
    assert "shop1_user1" in live_heartbeat_keys()


def test_heartbeat_status_for():
    from core.channel_facade import heartbeat_status_for

    mgr = ConnectionStatusManager()
    mgr.update_status("s2", "u2", "cs", ConnectionState.CONNECTING)
    with patch("core.channel_facade._status_manager", return_value=mgr):
        row = heartbeat_status_for("s2", "u2")
    assert row["connection_state"] == "connecting"


def test_heartbeat_status_all_marks_running():
    mgr = ConnectionStatusManager()
    mgr.update_status("570414651", "184046586", "cs1", ConnectionState.CONNECTED)

    ch = MagicMock()
    ch._heartbeat_tasks = {
        "570414651_184046586": MagicMock(done=MagicMock(return_value=False))
    }
    ch.heartbeat_config = MagicMock(
        enable_heartbeat=True, heartbeat_interval=30.0, max_heartbeat_failures=3
    )
    register_pdd_channel(ch)

    with patch("core.channel_facade._status_manager", return_value=mgr):
        out = heartbeat_status_all()

    row = out["570414651_184046586"]
    assert row["heartbeat_running"] is True
    assert row["heartbeat_enabled"] is True
    assert row["connection_state"] == "connected"


def test_build_heartbeat_status_done_task_not_running():
    mgr = ConnectionStatusManager()
    mgr.update_status("s1", "u1", "cs", ConnectionState.CONNECTED)
    ch = MagicMock()
    ch._heartbeat_tasks = {"s1_u1": MagicMock(done=MagicMock(return_value=True))}
    ch.heartbeat_config = MagicMock(
        enable_heartbeat=True, heartbeat_interval=30.0, max_heartbeat_failures=3
    )
    ch.status_manager = mgr
    register_pdd_channel(ch)

    row = build_heartbeat_status("s1", "u1", channel=ch, status_manager=mgr)
    assert row["heartbeat_running"] is False
    assert row["heartbeat_enabled"] is True
