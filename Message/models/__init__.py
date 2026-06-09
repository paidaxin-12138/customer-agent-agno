# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
Message模块数据模型
"""

# 导入根目录的message.py
from ..message import ChatMessage
from .queue_models import MessageWrapper, QueueStats

__all__ = [
    'ChatMessage',
    'MessageWrapper',
    'QueueStats'
]