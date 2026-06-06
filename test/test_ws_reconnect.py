"""WebSocket 重连逻辑单测。"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from Channel.pinduoduo.ws_config import ReconnectConfig
from Channel.pinduoduo.ws_reconnect import connect_with_retry, interruptible_sleep
from core.connection_status import ConnectionState, ConnectionStatusManager


@pytest.fixture(autouse=True)
def _clear_connection_status():
    ConnectionStatusManager().clear_all()
    yield
    ConnectionStatusManager().clear_all()


@pytest.mark.asyncio
async def test_interruptible_sleep_stops_when_event_set():
    mgr = ConnectionStatusManager()
    stop_events = {"s_u": asyncio.Event()}
    task = asyncio.create_task(
        interruptible_sleep(
            2.0,
            connection_key="s_u",
            shop_id="s",
            user_id="u",
            username="cs",
            stop_events=stop_events,
            status_manager=mgr,
        )
    )
    await asyncio.sleep(0.15)
    stop_events["s_u"].set()
    ok = await asyncio.wait_for(task, timeout=1.0)
    assert ok is False
    st = mgr.get_status("s", "u")
    assert st is not None
    assert st.state == ConnectionState.DISCONNECTED


@pytest.mark.asyncio
async def test_connect_with_retry_respects_max_attempts():
    mgr = ConnectionStatusManager()
    stop_events: dict = {}
    cfg = ReconnectConfig(
        max_attempts=2,
        reconnect_delay_sec=0.1,
        enable_auto_reconnect=True,
    )
    attempts = 0
    failures: list = []

    async def _fail_attempt(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("connect failed")

    await connect_with_retry(
        "shop1",
        "user1",
        "cs1",
        MagicMock(),
        failures.append,
        reconnect_config=cfg,
        stop_events=stop_events,
        status_manager=mgr,
        connect_attempt=_fail_attempt,
    )

    assert attempts == 2
    assert failures == ["连接失败，已达到最大重试次数"]
    st = mgr.get_status("shop1", "user1")
    assert st is not None
    assert st.state == ConnectionState.ERROR


@pytest.mark.asyncio
async def test_connect_with_retry_honors_stop_event():
    mgr = ConnectionStatusManager()
    key = "shop_stop_user_stop"
    stop_events = {key: asyncio.Event()}
    cfg = ReconnectConfig(max_attempts=0, reconnect_delay_sec=0.1)
    calls = 0

    async def _noop(*args, **kwargs):
        nonlocal calls
        calls += 1
        stop_events[key].set()

    await connect_with_retry(
        "shop_stop",
        "user_stop",
        "cs1",
        MagicMock(),
        MagicMock(),
        reconnect_config=cfg,
        stop_events=stop_events,
        status_manager=mgr,
        connect_attempt=_noop,
    )

    assert calls == 1
    assert stop_events[key].is_set()


@pytest.mark.asyncio
async def test_connect_with_retry_stops_on_credential_error():
    from Channel.pinduoduo.ws_errors import WsCredentialError

    mgr = ConnectionStatusManager()
    stop_events: dict = {}
    cfg = ReconnectConfig(max_attempts=0, reconnect_delay_sec=0.1)
    failures: list[str] = []
    attempts = 0

    async def _cred_fail(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise WsCredentialError("Cookie 过期")

    await connect_with_retry(
        "shop1",
        "user1",
        "cs1",
        MagicMock(),
        failures.append,
        reconnect_config=cfg,
        stop_events=stop_events,
        status_manager=mgr,
        connect_attempt=_cred_fail,
    )

    assert attempts == 1
    assert failures == ["Cookie 过期"]
    st = mgr.get_status("shop1", "user1")
    assert st is not None
    assert st.state == ConnectionState.ERROR
