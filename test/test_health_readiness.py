# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""健康检查就绪逻辑单元测试。"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from core.connection_status import ConnectionState, ConnectionStatus


def test_evaluate_readiness_no_connections(monkeypatch):
    from core.health_server import _evaluate_readiness

    class _Mgr:
        def get_all_status(self):
            return []

    monkeypatch.setattr(
        "core.connection_status.ConnectionStatusManager",
        lambda: _Mgr(),
    )
    ready, reason, _ = _evaluate_readiness()
    assert ready is False
    assert reason == "no_connection_registered"


def test_evaluate_readiness_ws_without_consumer(monkeypatch):
    from core.health_server import _evaluate_readiness

    status = ConnectionStatus(
        shop_id="s1",
        user_id="u1",
        username="test",
        state=ConnectionState.CONNECTED,
    )

    class _Mgr:
        def get_all_status(self):
            return [status]

    class _ConsumerMgr:
        def get_consumer(self, _name):
            return None

    monkeypatch.setattr(
        "core.connection_status.ConnectionStatusManager",
        lambda: _Mgr(),
    )
    monkeypatch.setattr(
        "Message.core.consumer.message_consumer_manager",
        _ConsumerMgr(),
    )
    ready, reason, detail = _evaluate_readiness()
    assert ready is False
    assert reason == "no_running_consumer_for_connected_shop"
    assert detail["ws_connected"] == 1


def test_evaluate_readiness_reconnect_grace(monkeypatch):
    from core.health_server import _evaluate_readiness

    s1 = ConnectionStatus("s1", "u1", "a", ConnectionState.CONNECTED)
    s2 = ConnectionStatus(
        "s2",
        "u2",
        "b",
        ConnectionState.CONNECTED,
        last_connect_time=datetime.now(),
    )

    class _Mgr:
        def get_all_status(self):
            return [s1, s2]

    running_consumer = MagicMock()
    running_consumer.is_running.return_value = True

    class _ConsumerMgr:
        def get_consumer(self, name):
            if name == "pdd_s1_u1":
                return running_consumer
            return None

    monkeypatch.setattr("core.connection_status.ConnectionStatusManager", lambda: _Mgr())
    monkeypatch.setattr(
        "Message.core.consumer.message_consumer_manager",
        _ConsumerMgr(),
    )
    ready, reason, detail = _evaluate_readiness()
    assert ready is True
    assert reason == "reconnect_grace"
    assert detail["readiness_grace_active"] is True
    assert len(detail["consumers_in_grace"]) == 1
    assert detail["consumers_in_grace"][0]["shop_id"] == "s2"


def test_evaluate_readiness_grace_expired(monkeypatch):
    from core.health_server import _evaluate_readiness

    s1 = ConnectionStatus("s1", "u1", "a", ConnectionState.CONNECTED)
    s2 = ConnectionStatus(
        "s2",
        "u2",
        "b",
        ConnectionState.CONNECTED,
        last_connect_time=datetime.now() - timedelta(seconds=120),
    )

    class _Mgr:
        def get_all_status(self):
            return [s1, s2]

    running_consumer = MagicMock()
    running_consumer.is_running.return_value = True

    class _ConsumerMgr:
        def get_consumer(self, name):
            if name == "pdd_s1_u1":
                return running_consumer
            return None

    monkeypatch.setattr("core.connection_status.ConnectionStatusManager", lambda: _Mgr())
    monkeypatch.setattr(
        "Message.core.consumer.message_consumer_manager",
        _ConsumerMgr(),
    )
    ready, reason, detail = _evaluate_readiness()
    assert ready is False
    assert reason == "not_all_connected_shops_ready"
    assert detail.get("consumers_in_grace") == []


def test_evaluate_readiness_grace_disabled(monkeypatch):
    from core.health_server import _evaluate_readiness

    monkeypatch.setenv("READINESS_RECONNECT_GRACE_SEC", "0")
    s1 = ConnectionStatus("s1", "u1", "a", ConnectionState.CONNECTED)
    s2 = ConnectionStatus(
        "s2",
        "u2",
        "b",
        ConnectionState.CONNECTED,
        last_connect_time=datetime.now(),
    )

    class _Mgr:
        def get_all_status(self):
            return [s1, s2]

    running_consumer = MagicMock()
    running_consumer.is_running.return_value = True

    class _ConsumerMgr:
        def get_consumer(self, name):
            if name == "pdd_s1_u1":
                return running_consumer
            return None

    monkeypatch.setattr("core.connection_status.ConnectionStatusManager", lambda: _Mgr())
    monkeypatch.setattr(
        "Message.core.consumer.message_consumer_manager",
        _ConsumerMgr(),
    )
    ready, reason, _ = _evaluate_readiness()
    assert ready is False
    assert reason == "not_all_connected_shops_ready"
