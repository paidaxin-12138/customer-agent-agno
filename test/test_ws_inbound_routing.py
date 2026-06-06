"""WebSocket 入站路由单测。"""
from __future__ import annotations

from bridge.context import ChannelType, Context, ContextType
from Channel.pinduoduo.ws_inbound_routing import (
    InboundRoute,
    classify_inbound_route,
    should_process_immediately,
    should_queue_message,
)


def _ctx(msg_type: ContextType, *, from_user: str = "user") -> Context:
    kwargs = type(
        "K",
        (),
        {"from_user": from_user, "from_uid": "b1", "shop_id": "s", "user_id": "u"},
    )()
    return Context(
        type=msg_type,
        content="hi",
        channel_type=ChannelType.PINDUODUO,
        kwargs=kwargs,
    )


def test_text_message_queues():
    ctx = _ctx(ContextType.TEXT)
    assert should_queue_message(ctx) is True
    assert classify_inbound_route(ctx) == InboundRoute.QUEUE


def test_transfer_immediate():
    ctx = _ctx(ContextType.TRANSFER, from_user="system")
    assert should_process_immediately(ctx) is True
    assert classify_inbound_route(ctx) == InboundRoute.IMMEDIATE


def test_unknown_buyer_type_force_queue():
    ctx = _ctx(ContextType.SYSTEM_BIZ, from_user="user")
    assert classify_inbound_route(ctx) == InboundRoute.FORCE_QUEUE


def test_unknown_non_buyer_ignored():
    ctx = _ctx(ContextType.SYSTEM_BIZ, from_user="system")
    assert classify_inbound_route(ctx) == InboundRoute.IGNORE
