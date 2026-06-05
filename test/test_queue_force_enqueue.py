"""队列满时强制入队：丢弃最旧消息。"""

import asyncio

import pytest

from Message.core.queue import SimpleMessageQueue
from Message.models.queue_models import QueueConfig
from bridge.context import Context, ContextType, ChannelType


def _ctx(uid: str) -> Context:
    kwargs = type("Kwargs", (), {"from_uid": uid, "from_user": "user"})()
    return Context(
        type=ContextType.TEXT,
        channel_type=ChannelType.PINDUODUO,
        content=f"msg-{uid}",
        kwargs=kwargs,
    )


@pytest.mark.asyncio
async def test_force_enqueue_drops_oldest(monkeypatch):
    monkeypatch.setattr(
        "Message.core.queue.get_config",
        lambda k, d=None: True if k == "chat.queue_force_enqueue" else d,
    )
    q = SimpleMessageQueue("test", QueueConfig(max_size=2, enable_deduplication=False))
    await q.put(_ctx("1"))
    await q.put(_ctx("2"))
    assert q.size() == 2
    mid = await q.put(_ctx("3"))
    assert mid
    assert q.size() == 2
    first = await q.get()
    second = await q.get()
    assert first.context.content == "msg-2"
    assert second.context.content == "msg-3"


@pytest.mark.asyncio
async def test_queue_full_raises_without_force(monkeypatch):
    monkeypatch.setattr(
        "Message.core.queue.get_config",
        lambda k, d=None: False if k == "chat.queue_force_enqueue" else d,
    )
    q = SimpleMessageQueue("test", QueueConfig(max_size=1, enable_deduplication=False))
    await q.put(_ctx("1"))
    with pytest.raises(RuntimeError, match="Queue is full"):
        await q.put(_ctx("2"))
