"""健康检查就绪逻辑单元测试。"""
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
