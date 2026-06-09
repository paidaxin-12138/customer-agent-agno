# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""消息队列去重行为。"""
import pytest

from bridge.context import ChannelType, Context, ContextType, PinduoduoKwargs
from Message.core.queue import SimpleMessageQueue
from Message.models.queue_models import QueueConfig


def _ctx(text: str, buyer: str = "buyer_1"):
    return Context(
        type=ContextType.TEXT,
        content=text,
        channel_type=ChannelType.PINDUODUO,
        kwargs=PinduoduoKwargs(
            shop_id="s1",
            user_id="u1",
            from_uid=buyer,
            username="b",
        ),
    )


@pytest.mark.asyncio
async def test_dedup_returns_empty_without_enqueue():
    q = SimpleMessageQueue(
        "dedup_test",
        QueueConfig(max_size=10, enable_deduplication=True, deduplication_window=300),
    )
    mid1 = await q.put(_ctx("相同内容"))
    mid2 = await q.put(_ctx("相同内容"))
    assert mid1
    assert mid2 == ""
    assert q.size() == 1
