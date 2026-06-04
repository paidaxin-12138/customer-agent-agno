"""Phase 3：stage 阶段隔离门禁测试。"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from bridge.context import ChannelType, Context, ContextType
from Message.handlers.address_change_handler import AddressChangeHandler
from Message.handlers.ai_handler import AIReplyHandler
from Message.handlers.order_logistics_handler import OrderLogisticsHandler
from Message.core.handlers import CatchAllHandler


def _ctx(text: str = "改地址") -> Context:
    kwargs = type(
        "Kwargs",
        (),
        {"from_uid": "b1", "shop_id": "s1", "user_id": "u1", "raw_data": {}},
    )()
    return Context(
        type=ContextType.TEXT,
        content=text,
        channel_type=ChannelType.PINDUODUO,
        kwargs=kwargs,
    )


@pytest.mark.parametrize(
    "stage,handler_cls,content,expected",
    [
        ("address_change", AddressChangeHandler, "改收货地址", True),
        ("await_confirm", AddressChangeHandler, "确认", True),
        ("await_confirm", AddressChangeHandler, "查物流", False),
        ("address_change", OrderLogisticsHandler, "查物流", False),
        ("address_change", AIReplyHandler, "多少钱", False),
        ("logistics", OrderLogisticsHandler, "查物流到哪了", True),
        ("logistics", AddressChangeHandler, "改地址", False),
        ("product_qa", AIReplyHandler, "你好", True),
        ("product_qa", AddressChangeHandler, "改地址", False),
        ("idle", CatchAllHandler, "任意", True),
        ("address_change", CatchAllHandler, "任意", False),
    ],
)
def test_stage_gate_can_handle(stage, handler_cls, content, expected):
    ctx = _ctx(content)
    with patch(
        "Agent.CustomerAgent.conversation_memory.get_current_stage",
        return_value=stage,
    ):
        handler = handler_cls() if handler_cls is not AIReplyHandler else AIReplyHandler(bot=None)
        assert handler.can_handle(ctx) is expected


def test_keyword_handler_allowed_in_non_idle_stage():
    from Message.handlers.keyword_handler import KeywordDetectionHandler

    ctx = _ctx("转人工")
    with patch(
        "Agent.CustomerAgent.conversation_memory.get_current_stage",
        return_value="after_sales",
    ):
        assert KeywordDetectionHandler().can_handle(ctx) is True
