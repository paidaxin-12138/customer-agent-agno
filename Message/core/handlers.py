"""
简化的消息处理器基类
提取核心接口，移除复杂的实现
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
from bridge.context import Context
from utils.logger_loguru import get_logger


class MessageHandler(ABC):
    """消息处理器基类"""

    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)

    @abstractmethod
    def can_handle(self, context: Context) -> bool:
        """
        判断是否能处理该消息

        Args:
            context: Context格式的消息

        Returns:
            bool: 是否能处理
        """
        pass

    @abstractmethod
    async def handle(self, context: Context, metadata: Dict[str, Any]) -> bool:
        """
        处理消息

        Args:
            context: Context格式的消息
            metadata: 消息元数据

        Returns:
            bool: 是否处理成功
        """
        pass

    async def on_error(self, context: Context, error: Exception) -> None:
        """
        错误处理回调（可选重写）

        Args:
            context: 消息上下文
            error: 错误对象
        """
        self.logger.error(f"Handler {self.__class__.__name__} error: {error}")


class TypeBasedHandler(MessageHandler):
    """基于消息类型的处理器"""

    def __init__(self, supported_types: set):
        super().__init__()
        self.supported_types = supported_types

    def can_handle(self, context: Context) -> bool:
        """检查消息类型"""
        return context.type in self.supported_types


class ChannelBasedHandler(MessageHandler):
    """基于渠道类型的处理器"""

    def __init__(self, supported_channels: set):
        super().__init__()
        self.supported_channels = supported_channels

    def can_handle(self, context: Context) -> bool:
        """检查渠道类型"""
        # 处理 channel_type 可能为 None 的情况
        channel_type = context.channel_type
        if channel_type is None:
            return False

        # 支持字符串和枚举类型
        if hasattr(channel_type, 'value'):
            channel_str = str(channel_type.value)
        else:
            channel_str = str(channel_type)

        return channel_str in {str(ch) for ch in self.supported_channels}


class CatchAllHandler(MessageHandler):
    """链末兜底：记日志 + 可选向买家发送安抚（与 consumer fallback 二选一生效）。"""

    _DEFAULT_COMFORT = (
        "亲，消息已收到，客服稍后会回复您；如需人工请回复「人工」。"
    )

    def __init__(self):
        super().__init__()

    def can_handle(self, context: Context) -> bool:
        return True

    async def handle(self, context: Context, metadata: Dict[str, Any]) -> bool:
        from config import config
        from utils.log_redact import redact_log_payload

        user_id = metadata.get("user_id", "unknown")
        message_id = metadata.get("message_id", "unknown")
        safe_content = redact_log_payload(
            context.content if isinstance(context.content, (str, dict)) else str(context.content)
        )

        self.logger.info("=== CatchAll 消息记录 ===")
        self.logger.info(f"用户ID: {user_id} 消息ID: {message_id}")
        self.logger.info(f"类型: {context.type} 渠道: {context.channel_type}")
        self.logger.info(f"内容(脱敏): {safe_content}")

        if not bool(config.get("chat.catchall_comfort_enabled", True)):
            return False

        notice = str(
            config.get("chat.catchall_comfort_notice") or self._DEFAULT_COMFORT
        ).strip()
        if not notice:
            return False

        shop_id = metadata.get("shop_id")
        seller_id = metadata.get("user_id")
        from_uid = metadata.get("from_uid")
        if not all([shop_id, seller_id, from_uid]):
            return False

        try:
            from Message.handlers.channel_send import send_text_to_buyer

            ok = await send_text_to_buyer(
                shop_id,
                seller_id,
                from_uid,
                notice,
                context=context,
                metadata=metadata,
            )
            if ok:
                self.logger.info("CatchAll 已发送链末安抚")
            return ok
        except Exception as e:
            self.logger.warning(f"CatchAll 安抚发送失败: {e}")
            return False