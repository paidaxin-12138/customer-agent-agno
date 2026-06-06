"""拼多多 WebSocket 建连（从 PDDChannel.init 抽离）。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict

import websockets

from Channel.pinduoduo.ws_config import build_pdd_ws_url

# 与平台兼容的客户端参数（ping 间隔勿与 ws_heartbeat 冲突过大）
WS_CLIENT_KWARGS: Dict[str, Any] = {
    "ping_interval": 60,
    "ping_timeout": 30,
    "max_size": 10**7,
    "compression": None,
    "close_timeout": 10,
}


@asynccontextmanager
async def connect_pdd_ws(access_token: str) -> AsyncIterator[Any]:
    """建立拼多多客服 WebSocket 连接。"""
    full_url = build_pdd_ws_url(access_token)
    async with websockets.connect(full_url, **WS_CLIENT_KWARGS) as websocket:
        yield websocket
