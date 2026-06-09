# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""WebSocket 入站消息路由（immediate / queue / ignore）。"""
from __future__ import annotations

from enum import Enum

from bridge.context import Context, ContextType


class InboundRoute(str, Enum):
    IMMEDIATE = "immediate"
    QUEUE = "queue"
    FORCE_QUEUE = "force_queue"
    IGNORE = "ignore"


_IMMEDIATE_TYPES = frozenset(
    {
        ContextType.SYSTEM_STATUS,
        ContextType.AUTH,
        ContextType.WITHDRAW,
        ContextType.SYSTEM_HINT,
        ContextType.MALL_CS,
        ContextType.MALL_SYSTEM_MSG,
        ContextType.TRANSFER,
    }
)

_QUEUE_TYPES = frozenset(
    {
        ContextType.TEXT,
        ContextType.IMAGE,
        ContextType.VIDEO,
        ContextType.EMOTION,
        ContextType.GOODS_INQUIRY,
        ContextType.ORDER_INFO,
        ContextType.GOODS_CARD,
        ContextType.GOODS_SPEC,
    }
)


def should_process_immediately(context: Context) -> bool:
    return context.type in _IMMEDIATE_TYPES


def should_queue_message(context: Context) -> bool:
    return context.type in _QUEUE_TYPES


def classify_inbound_route(context: Context) -> InboundRoute:
    if should_process_immediately(context):
        return InboundRoute.IMMEDIATE
    if should_queue_message(context):
        return InboundRoute.QUEUE
    from_user = str(getattr(getattr(context, "kwargs", None), "from_user", "") or "")
    if from_user == "user":
        return InboundRoute.FORCE_QUEUE
    return InboundRoute.IGNORE
