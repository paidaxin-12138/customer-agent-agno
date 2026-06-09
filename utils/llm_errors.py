# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""LLM / HTTP 传输层瞬时错误判定（供 AI Handler 与 Agent 复用）。"""
from __future__ import annotations

import asyncio
import errno
from typing import Optional

_DEFAULT_UNKNOWN_NOTICE = (
    "亲，我暂时还不清楚，您可以描述得更详细些，或者我帮您转人工客服？"
)


def get_ai_unknown_fallback_notice() -> str:
    try:
        from config import config

        custom = (config.get("chat.ai_unknown_fallback_notice") or "").strip()
        if custom:
            return custom
    except Exception:
        pass
    return _DEFAULT_UNKNOWN_NOTICE


def should_replace_pm_fallback_reply(ai_reply: Optional[str]) -> bool:
    """
    LLM 回复含「产品经理」且为低置信度兜底时，改用预设未知话术。
    默认不转人工（chat.ai_fallback_to_human_on_unknown=false）。
    """
    t = (ai_reply or "").strip()
    if not t or "产品经理" not in t:
        return False
    try:
        from config import config

        if bool(config.get("chat.ai_fallback_to_human_on_unknown", False)):
            return False
    except Exception:
        pass
    return True


def sanitize_ai_reply_content(ai_reply: Optional[str]) -> str:
    """将含产品经理的低置信度回复替换为配置兜底话术。"""
    if should_replace_pm_fallback_reply(ai_reply):
        from utils.logger_loguru import get_logger

        get_logger("LLMErrors").info(
            "LLM 回复含产品经理兜底话术，替换为未知问题兜底 notice"
        )
        return get_ai_unknown_fallback_notice()
    return (ai_reply or "").strip()


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
