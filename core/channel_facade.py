# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""UI 与渠道层的稳定门面（查询连接状态，不依赖 PDDChannel 内部）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.connection_status import (
    ConnectionState,
    ConnectionStatus,
    ConnectionStatusManager,
)


def _status_manager() -> ConnectionStatusManager:
    try:
        from core.di_container import container

        return container.get(ConnectionStatusManager)
    except Exception:
        return ConnectionStatusManager()


def create_pdd_channel(**kwargs: Any):
    """创建拼多多 WebSocket 渠道实例（UI / 后台线程统一入口）。"""
    from Channel.pinduoduo.pdd_channel import PDDChannel

    return PDDChannel(**kwargs)


def list_connection_status() -> List[ConnectionStatus]:
    """所有账号的实时 WebSocket 连接状态。"""
    return _status_manager().get_all_status()


def list_connected_accounts() -> List[ConnectionStatus]:
    """当前已 CONNECTED 的账号。"""
    return [
        s for s in list_connection_status() if s.state == ConnectionState.CONNECTED
    ]


def get_connected_count() -> int:
    return _status_manager().get_connected_count()


def connection_summary() -> Dict[str, int]:
    """连接状态汇总（供监控/仪表盘）。"""
    summary = {
        "total": 0,
        "connected": 0,
        "connecting": 0,
        "reconnecting": 0,
        "error": 0,
        "disconnected": 0,
    }
    for status in list_connection_status():
        summary["total"] += 1
        key = status.state.value
        if key in summary:
            summary[key] += 1
    return summary


def heartbeat_status_all() -> Dict[str, Dict[str, Any]]:
    """各连接状态；心跳运行态来自已注册 PDDChannel 实例。"""
    from core.pdd_channel_registry import build_heartbeat_status

    mgr = _status_manager()
    out: Dict[str, Dict[str, Any]] = {}
    for status in mgr.get_all_status():
        key = f"{status.shop_id}_{status.user_id}"
        row = build_heartbeat_status(
            status.shop_id, status.user_id, status_manager=mgr
        )
        row["reconnect_count"] = status.reconnect_count
        out[key] = row
    return out


def heartbeat_status_for(shop_id: str, user_id: str) -> Dict[str, Any]:
    """单账号心跳与连接状态（门面入口）。"""
    from core.pdd_channel_registry import build_heartbeat_status

    return build_heartbeat_status(shop_id, user_id, status_manager=_status_manager())


def account_display_status(shop_id: str, user_id: str) -> Optional[str]:
    """
    供 UI 展示的 WebSocket 状态文案。
    返回 ``在线`` / ``连接中``，无 WS 记录时返回 None。
    """
    for st in list_connection_status():
        if str(st.shop_id) == str(shop_id) and str(st.user_id) == str(user_id):
            if st.state == ConnectionState.CONNECTED:
                return "在线"
            if st.state in (ConnectionState.CONNECTING, ConnectionState.RECONNECTING):
                return "连接中"
            break
    return None


def connection_status_for(shop_id: str, user_id: str) -> Optional[ConnectionStatus]:
    return _status_manager().get_status(str(shop_id), str(user_id))
