"""WebSocket 重连配置加载单测。"""
from __future__ import annotations

from unittest.mock import patch

from Channel.pinduoduo.ws_config import (
    HeartbeatConfig,
    ReconnectConfig,
    apply_heartbeat_config,
    apply_reconnect_config,
    load_reconnect_config,
    load_ws_message_concurrency,
)


def test_load_reconnect_config_defaults():
    with patch("config.get_config", side_effect=lambda key, default=None: default):
        cfg = load_reconnect_config()
    assert isinstance(cfg, ReconnectConfig)
    assert cfg.reconnect_delay_sec == 5.0
    assert cfg.max_attempts == 0
    assert cfg.enable_auto_reconnect is True


def test_load_reconnect_config_clamps_delay():
    def _cfg(key, default=None):
        if key == "chat.ws_reconnect_delay_sec":
            return 999
        if key == "chat.ws_reconnect_max_attempts":
            return 3
        if key == "chat.ws_auto_reconnect_enabled":
            return False
        return default

    with patch("config.get_config", side_effect=_cfg):
        cfg = load_reconnect_config()
    assert cfg.reconnect_delay_sec == 120.0
    assert cfg.initial_delay == 120.0
    assert cfg.max_attempts == 3
    assert cfg.enable_auto_reconnect is False


def test_apply_reconnect_config():
    cfg = ReconnectConfig()
    apply_reconnect_config(cfg, max_attempts=5, enable_auto_reconnect=False)
    assert cfg.max_attempts == 5
    assert cfg.enable_auto_reconnect is False


def test_apply_heartbeat_config():
    cfg = HeartbeatConfig()
    apply_heartbeat_config(cfg, heartbeat_interval=45.0, max_heartbeat_failures=2)
    assert cfg.heartbeat_interval == 45.0
    assert cfg.max_heartbeat_failures == 2


def test_load_ws_message_concurrency_clamps():
    with patch("config.get_config", return_value=999):
        assert load_ws_message_concurrency() == 32
    with patch("config.get_config", return_value=1):
        assert load_ws_message_concurrency() == 4


def test_queue_name_for_shop():
    from Channel.pinduoduo.ws_config import queue_name_for_shop

    assert queue_name_for_shop("570414651") == "pdd_570414651"


def test_queue_name_for_account():
    from Channel.pinduoduo.ws_config import queue_name_for_account, queue_name_for_shop

    assert queue_name_for_account("570414651", "184046586") == "pdd_570414651_184046586"
    assert queue_name_for_shop("570414651", "184046586") == "pdd_570414651_184046586"
