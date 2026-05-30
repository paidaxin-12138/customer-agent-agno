"""LLM / HTTP 传输层瞬时错误判定（供 AI Handler 与 Agent 复用）。"""
from __future__ import annotations

import asyncio
import errno
from typing import Optional


def is_transient_llm_transport_error(exc: BaseException) -> bool:
    """
    判定是否为可重试的瞬时网络/传输错误（EPIPE、连接重置、httpx 超时等）。
    """
    seen: set[int] = set()
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(
            cur,
            (
                BrokenPipeError,
                ConnectionResetError,
                ConnectionAbortedError,
                asyncio.TimeoutError,
            ),
        ):
            return True
        if isinstance(cur, OSError):
            en = getattr(cur, "errno", None)
            if en in (errno.EPIPE, errno.ECONNRESET, errno.ETIMEDOUT, errno.ECONNABORTED):
                return True
        name = type(cur).__name__
        if name in (
            "ReadError",
            "WriteError",
            "RemoteProtocolError",
            "LocalProtocolError",
            "ConnectError",
            "ReadTimeout",
            "WriteTimeout",
            "ConnectTimeout",
        ):
            return True
        cur = cur.__cause__ or cur.__context__
    return False
