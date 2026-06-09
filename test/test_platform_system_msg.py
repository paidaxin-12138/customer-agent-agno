# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""平台文明用语系统消息识别。"""
from bridge.context import Context, ContextType, ChannelType, PinduoduoKwargs
from utils.platform_system_msg import (
    is_platform_civility_content,
    is_platform_civility_message,
    is_marked_platform_civility,
    mark_platform_civility_context,
)


def test_civility_content_detected():
    assert is_platform_civility_content("请文明用语，共建和谐购物环境")
    assert not is_platform_civility_content("亲，这款有现货哦")


def test_mall_system_msg_civility():
    import json

    ctx = Context(
        type=ContextType.MALL_SYSTEM_MSG,
        content=json.dumps({"text": "请文明用语"}, ensure_ascii=False),
        channel_type=ChannelType.PINDUODUO,
    )
    assert is_platform_civility_message(ctx)


def test_mall_cs_civility():
    ctx = Context(
        type=ContextType.MALL_CS,
        content="请文明用语",
        channel_type=ChannelType.PINDUODUO,
    )
    assert is_platform_civility_message(ctx)


def test_mark_platform_civility():
    ctx = Context(
        type=ContextType.TEXT,
        content="hi",
        kwargs=PinduoduoKwargs(raw_data={"msg": 1}),
    )
    mark_platform_civility_context(ctx)
    assert is_marked_platform_civility(ctx)
