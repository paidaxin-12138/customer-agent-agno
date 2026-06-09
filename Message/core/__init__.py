# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
Message模块核心功能
包含简化的消息队列、消费者和处理器基类
"""

from .queue import SimpleMessageQueue, QueueManager
from .consumer import MessageConsumer
from .handlers import MessageHandler, TypeBasedHandler, ChannelBasedHandler

__all__ = [
    'SimpleMessageQueue',
    'QueueManager',
    'MessageConsumer',
    'MessageHandler',
    'TypeBasedHandler',
    'ChannelBasedHandler'
]