"""WebSocket 心跳逻辑单测。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from Channel.pinduoduo.ws_config import HeartbeatConfig
from Channel.pinduoduo.ws_heartbeat import run_heartbeat_loop
from core.connection_status import ConnectionState, ConnectionStatusManager


@pytest.fixture(autouse=True)
def _clear_connection_status():
    ConnectionStatusManager().clear_all()
    yield
    ConnectionStatusManager().clear_all()


@pytest.mark.asyncio
async def test_heartbeat_marks_error_after_max_failures():
    mgr = ConnectionStatusManager()
    mgr.update_status("s", "u", "cs", ConnectionState.CONNECTED)
    stop = asyncio.Event()
    cfg = HeartbeatConfig(
        heartbeat_interval=0.05,
        heartbeat_timeout=0.01,
        max_heartbeat_failures=2,
    )
    ws = MagicMock()
    ws.ping = AsyncMock(side_effect=RuntimeError("ping failed"))
    finished: list[str] = []

    task = asyncio.create_task(
        run_heartbeat_loop(
            ws,
            "s",
            "u",
            "cs",
            stop,
            config=cfg,
            status_manager=mgr,
            on_finished=finished.append,
        )
    )
    await asyncio.wait_for(task, timeout=2.0)

    st = mgr.get_status("s", "u")
    assert st is not None
    assert st.state == ConnectionState.ERROR
    assert "心跳检查失败" in (st.last_error or "")
    assert finished == ["s_u"]
    assert ws.ping.await_count >= 2
