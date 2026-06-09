# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""WebSocket 重连与心跳配置（从 pdd_chnnel 抽离，便于单测与复用）。"""
from __future__ import annotations

from dataclasses import dataclass

PDD_WS_BASE_URL = "wss://m-ws.pinduoduo.com/"
PDD_WS_API_VERSION = "202506091557"


def connection_key(shop_id: str, user_id: str) -> str:
    return f"{shop_id}_{user_id}"


def queue_name_for_account(shop_id: str, user_id: str) -> str:
    """账号级消息队列名（多店多账号：每连接独立队列与消费者）。"""
    sid = str(shop_id or "").strip()
    uid = str(user_id or "").strip()
    if not sid or not uid:
        raise ValueError("queue_name_for_account requires shop_id and user_id")
    return f"pdd_{sid}_{uid}"


def queue_name_for_shop(shop_id: str, user_id: str | None = None) -> str:
    """
    消息队列名。传入 user_id 时与 queue_name_for_account 一致；
    仅 shop_id 时保留旧名 pdd_{shop_id}（兼容测试/迁移）。
    """
    if user_id is not None and str(user_id).strip():
        return queue_name_for_account(shop_id, user_id)
    return f"pdd_{shop_id}"


def build_pdd_ws_url(
    access_token: str,
    *,
    base_url: str = PDD_WS_BASE_URL,
    api_version: str = PDD_WS_API_VERSION,
) -> str:
    params = {
        "access_token": access_token,
        "role": "mall_cs",
        "client": "web",
        "version": api_version,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{base_url}?{query}"


@dataclass
class ReconnectConfig:
    """重连配置（max_attempts=0 表示无限重试）"""

    max_attempts: int = 0
    reconnect_delay_sec: float = 5.0
    initial_delay: float = 5.0
    max_delay: float = 60.0
    backoff_factor: float = 1.0
    enable_auto_reconnect: bool = True


@dataclass
class HeartbeatConfig:
    """心跳检查配置"""

    enable_heartbeat: bool = True
    heartbeat_interval: float = 30.0
    heartbeat_timeout: float = 10.0
    health_check_interval: float = 60.0
    max_heartbeat_failures: int = 3


def load_reconnect_config() -> ReconnectConfig:
    """从 config.json 读取 chat.ws_* 重连项，非法值回退默认。"""
    cfg = ReconnectConfig()
    try:
        from config import get_config

        delay = float(get_config("chat.ws_reconnect_delay_sec", 5) or 5)
        cfg.reconnect_delay_sec = max(3.0, min(delay, 120.0))
        cfg.initial_delay = cfg.reconnect_delay_sec
        max_att = int(get_config("chat.ws_reconnect_max_attempts", 0) or 0)
        cfg.max_attempts = max(0, max_att)
        cfg.enable_auto_reconnect = bool(
            get_config("chat.ws_auto_reconnect_enabled", True)
        )
        cfg.backoff_factor = float(get_config("chat.ws_reconnect_backoff_factor", 1.5) or 1.5)
        cfg.max_delay = float(get_config("chat.ws_reconnect_max_delay_sec", 60) or 60)
        cfg.backoff_factor = max(1.0, min(cfg.backoff_factor, 3.0))
        cfg.max_delay = max(10.0, min(cfg.max_delay, 300.0))
    except (TypeError, ValueError):
        pass
    return cfg


def load_ws_message_concurrency(default: int = 16) -> int:
    """入站消息并发上限（chat.ws_message_max_concurrent，4–32）。"""
    try:
        from config import get_config

        value = int(get_config("chat.ws_message_max_concurrent", default) or default)
    except (TypeError, ValueError):
        value = default
    return max(4, min(value, 32))


def apply_reconnect_config(
    cfg: ReconnectConfig,
    *,
    max_attempts: int | None = None,
    initial_delay: float | None = None,
    max_delay: float | None = None,
    backoff_factor: float | None = None,
    enable_auto_reconnect: bool | None = None,
) -> None:
    if max_attempts is not None:
        cfg.max_attempts = max_attempts
    if initial_delay is not None:
        cfg.initial_delay = initial_delay
    if max_delay is not None:
        cfg.max_delay = max_delay
    if backoff_factor is not None:
        cfg.backoff_factor = backoff_factor
    if enable_auto_reconnect is not None:
        cfg.enable_auto_reconnect = enable_auto_reconnect


def apply_heartbeat_config(
    cfg: HeartbeatConfig,
    *,
    enable_heartbeat: bool | None = None,
    heartbeat_interval: float | None = None,
    heartbeat_timeout: float | None = None,
    max_heartbeat_failures: int | None = None,
) -> None:
    if enable_heartbeat is not None:
        cfg.enable_heartbeat = enable_heartbeat
    if heartbeat_interval is not None:
        cfg.heartbeat_interval = heartbeat_interval
    if heartbeat_timeout is not None:
        cfg.heartbeat_timeout = heartbeat_timeout
    if max_heartbeat_failures is not None:
        cfg.max_heartbeat_failures = max_heartbeat_failures
