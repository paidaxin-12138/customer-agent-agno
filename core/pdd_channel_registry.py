# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""活跃 PDDChannel 实例弱引用注册表（供 channel_facade 读取心跳等运行时态）。"""
from __future__ import annotations

import weakref
from typing import Any, Dict, Optional, Set

from Channel.pinduoduo.ws_config import HeartbeatConfig, connection_key

_channels: weakref.WeakSet[Any] = weakref.WeakSet()


def register_pdd_channel(channel: Any) -> None:
    _channels.add(channel)


def iter_registered_channels():
    """返回当前存活的 PDDChannel 实例快照。"""
    return list(_channels)


def _channel_for_key(key: str) -> Optional[Any]:
    for channel in list(_channels):
        tasks = getattr(channel, "_heartbeat_tasks", None) or {}
        if key in tasks:
            return channel
    return None


def live_heartbeat_keys() -> Set[str]:
    """返回当前有心跳任务在跑的 connection_key 集合。"""
    keys: Set[str] = set()
    for channel in list(_channels):
        tasks = getattr(channel, "_heartbeat_tasks", None) or {}
        for key, task in list(tasks.items()):
            if task is not None and not task.done():
                keys.add(str(key))
    return keys


def heartbeat_detail_for(key: str) -> Dict[str, Any]:
    """从已注册 channel 实例聚合单连接心跳配置（首个命中）。"""
    channel = _channel_for_key(key)
    if channel is None:
        return {}
    tasks = getattr(channel, "_heartbeat_tasks", None) or {}
    cfg = getattr(channel, "heartbeat_config", None)
    task = tasks.get(key)
    return {
        "heartbeat_enabled": bool(getattr(cfg, "enable_heartbeat", False)),
        "heartbeat_running": task is not None and not task.done(),
        "heartbeat_interval": getattr(cfg, "heartbeat_interval", None),
        "max_failures": getattr(cfg, "max_heartbeat_failures", None),
    }


def build_heartbeat_status(
    shop_id: str,
    user_id: str,
    *,
    channel: Any = None,
    status_manager: Any = None,
) -> Dict[str, Any]:
    """单连接心跳 + 连接状态摘要（channel 优先，否则扫描注册表）。"""
    key = connection_key(shop_id, user_id)
    if channel is None:
        channel = _channel_for_key(key)

    cfg: Optional[HeartbeatConfig] = (
        getattr(channel, "heartbeat_config", None) if channel else None
    )
    tasks = getattr(channel, "_heartbeat_tasks", None) or {} if channel else {}
    task = tasks.get(key) if channel else None
    running = task is not None and not task.done() if task else key in live_heartbeat_keys()

    mgr = status_manager
    if mgr is None and channel is not None:
        mgr = getattr(channel, "status_manager", None)
    if mgr is None:
        from core.channel_facade import _status_manager

        mgr = _status_manager()

    status = mgr.get_status(shop_id, user_id) if mgr else None
    return {
        "connection_key": key,
        "heartbeat_enabled": bool(getattr(cfg, "enable_heartbeat", False)),
        "heartbeat_running": running,
        "heartbeat_interval": getattr(cfg, "heartbeat_interval", None),
        "max_failures": getattr(cfg, "max_heartbeat_failures", None),
        "connection_state": status.state.value if status else None,
        "last_error": status.last_error if status else None,
        "error_count": status.error_count if status else 0,
    }
