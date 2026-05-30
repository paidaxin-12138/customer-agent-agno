import asyncio

import pytest

from bridge.context import ChannelType, Context, ContextType
from Message.core.consumer import MessageConsumer
from Message.core.handlers import MessageHandler


class _CountingHandler(MessageHandler):
    def __init__(self):
        super().__init__()
        self.handled = 0

    def can_handle(self, context: Context) -> bool:
        return True

    async def handle(self, context: Context, metadata) -> bool:
        self.handled += 1
        return True


@pytest.mark.asyncio
async def test_consumer_bounded_workers_process_messages():
    consumer = MessageConsumer("test_q", max_concurrent=2)
    handler = _CountingHandler()
    consumer.add_handler(handler)

    ctx = Context(
        type=ContextType.TEXT,
        content="hi",
        channel_type=ChannelType.PINDUODUO,
        kwargs=type("K", (), {"from_uid": "u1", "shop_id": "s", "user_id": "u"})(),
    )
    from Message import put_message

    await consumer.start()
    await put_message(consumer.queue_name, ctx)
    await put_message(consumer.queue_name, ctx)
    await asyncio.sleep(0.5)
    await consumer.stop()
    assert handler.handled >= 1
