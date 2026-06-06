"""
拼多多 WebSocket 渠道（推荐入口，正确拼写）。

历史实现文件为 ``pdd_chnnel.py``（拼写保留兼容）。新代码请从此模块导入::

    from Channel.pinduoduo.pdd_channel import PDDChannel
    from core.channel_facade import list_connection_status, create_pdd_channel
"""
from __future__ import annotations

from typing import Dict, List

from Channel.pinduoduo.pdd_chnnel import PDDChannel
from Channel.pinduoduo.ws_context import context_struct_payload as _context_struct_payload
from core.channel_facade import (
    connection_summary,
    get_connected_count,
    heartbeat_status_all,
    list_connection_status,
)
from core.connection_status import ConnectionStatus


def get_pdd_connection_status() -> List[ConnectionStatus]:
    return list_connection_status()


def get_pdd_connected_count() -> int:
    return get_connected_count()


def get_pdd_connection_summary() -> Dict[str, int]:
    return connection_summary()


def get_pdd_heartbeat_status_all() -> Dict[str, Dict]:
    return heartbeat_status_all()


__all__ = [
    "PDDChannel",
    "_context_struct_payload",
    "get_pdd_connected_count",
    "get_pdd_connection_status",
    "get_pdd_connection_summary",
    "get_pdd_heartbeat_status_all",
]
