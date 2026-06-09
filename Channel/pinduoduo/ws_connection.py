# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""WebSocket 连接通用工具。"""
from __future__ import annotations

import asyncio
from typing import Any


async def safe_close_websocket(ws: Any, *, logger=None) -> None:
    """安全关闭 WebSocket（同步/异步 close 均兼容）。"""
    try:
        close_fn = getattr(ws, "close", None)
        if close_fn:
            result = close_fn()
            if asyncio.iscoroutine(result):
                await result
    except Exception as e:
        if logger is not None:
            logger.debug(f"关闭WebSocket失败: {e}")
