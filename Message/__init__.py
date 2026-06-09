# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""Message 包入口：队列、消费者、入队。"""
from __future__ import annotations

from bridge.context import Context

from .core.consumer import MessageConsumer, message_consumer_manager
from .core.queue import QueueManager, SimpleMessageQueue, queue_manager


async def put_message(queue_name: str, context: Context) -> str:
    """向指定队列放入 Context 消息。"""
    queue = queue_manager.get_or_create_queue(queue_name)
    return await queue.put(context)


__all__ = [
    "Context",
    "MessageConsumer",
    "QueueManager",
    "SimpleMessageQueue",
    "message_consumer_manager",
    "put_message",
    "queue_manager",
]
