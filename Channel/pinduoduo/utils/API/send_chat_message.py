"""发送聊天消息（与 send_message 一致，便于单独扩展）。"""
from .send_message import SendMessage


class SendChatMessage(SendMessage):
    """与 SendMessage 相同实现，命名对齐「聊天发送」模块。"""

    pass
