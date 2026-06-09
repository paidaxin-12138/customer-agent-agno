# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""拼多多等平台自动插入的系统提示（如「请文明用语」）识别。"""
from __future__ import annotations

from typing import Any, Optional

from bridge.context import Context, ContextType

CIVILITY_MARKERS = ("文明用语", "请文明", "文明沟通", "文明聊天")


def extract_context_text(context: Any) -> str:
    """从 Context 或 dict 中提取可匹配的文本。"""
    if context is None:
        return ""
    ctype = getattr(context, "type", None)
    content = getattr(context, "content", None)
    if ctype == ContextType.MALL_SYSTEM_MSG and isinstance(content, dict):
        return str(content.get("text") or content.get("content") or "")
    if isinstance(content, str):
        s = content.strip()
        if s.startswith("{") and "text" in s:
            try:
                import json

                data = json.loads(s)
                if isinstance(data, dict):
                    return str(data.get("text") or data.get("content") or s)
            except json.JSONDecodeError:
                pass
        return s
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or "")
    return str(content or "").strip()


def is_platform_civility_content(text: Optional[str]) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return any(m in t for m in CIVILITY_MARKERS)


def is_platform_civility_message(context: Any) -> bool:
    """平台自动文明用语提示（mall_system_msg / system_hint / mall_cs 文本）。"""
    if context is None:
        return False
    ctype = getattr(context, "type", None)
    text = extract_context_text(context)
    if not is_platform_civility_content(text):
        return False
    if ctype in (
        ContextType.MALL_SYSTEM_MSG,
        ContextType.SYSTEM_HINT,
        ContextType.MALL_CS,
    ):
        return True
    return False


def mark_platform_civility_context(context: Context) -> None:
    """在 raw_data 上打标，供下游 handler 识别。"""
    try:
        ku = getattr(context, "kwargs", None)
        if ku is None:
            return
        rd = dict(getattr(ku, "raw_data", None) or {})
        rd["_platform_civility"] = True
        if hasattr(ku, "model_copy"):
            object.__setattr__(context, "kwargs", ku.model_copy(update={"raw_data": rd}))
        else:
            ku.raw_data = rd
    except Exception:
        pass


def is_marked_platform_civility(context: Any) -> bool:
    try:
        ku = getattr(context, "kwargs", None)
        raw = getattr(ku, "raw_data", None) if ku else None
        if isinstance(raw, dict) and raw.get("_platform_civility"):
            return True
    except Exception:
        pass
    return is_platform_civility_message(context)
