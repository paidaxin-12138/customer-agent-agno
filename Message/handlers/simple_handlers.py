"""
简单消息处理器
提供基础的消息处理功能
"""

from typing import Optional, Dict, Any
from bridge.context import Context
from bridge.reply import Reply, ReplyType
from .base import BaseHandler
from utils.logger_loguru import get_logger

logger = get_logger("SimpleHandlers")


class SimpleReplyHandler(BaseHandler):
    """简单回复处理器"""
    
    def __init__(self, name: str = "SimpleReply"):
        """
        初始化简单回复处理器
        
        Args:
            name: 处理器名称
        """
        super().__init__(name)
    
    def handle(self, context: Context) -> Optional[Reply]:
        """
        处理消息并返回回复
        
        Args:
            context: 消息上下文
            
        Returns:
            回复对象，无法处理返回 None
        """
        content = context.content
        if not content:
            return None
        
        # 简单回复策略
        if "?" in content or "？" in content:
            return Reply(
                ReplyType.TEXT,
                "您好，收到您的问题，我们会尽快回复。"
            )
        
        return None


class TextOnlyHandler(BaseHandler):
    """仅文本处理器"""
    
    def __init__(self):
        """初始化仅文本处理器"""
        super().__init__("TextOnly")
    
    def handle(self, context: Context) -> Optional[Reply]:
        """
        处理消息
        
        Args:
            context: 消息上下文
            
        Returns:
            回复对象
        """
        # 只处理文本消息
        if context.type.value != 1:  # 非文本消息
            return None
        
        content = context.content
        if not content:
            return None
        
        # 简单文本处理
        return Reply(ReplyType.TEXT, f"收到：{content}")


class LoggingHandler(BaseHandler):
    """日志记录处理器"""
    
    def __init__(self):
        """初始化日志记录处理器"""
        super().__init__("Logging")
    
    def handle(self, context: Context) -> Optional[Reply]:
        """
        记录消息日志
        
        Args:
            context: 消息上下文
            
        Returns:
            None (仅记录日志)
        """
        # 记录消息
        self.logger.info(f"[消息] {context.type}: {context.content}")
        
        # 记录用户信息
        if hasattr(context, 'kwargs'):
            user_id = context.kwargs.get('from_uid', 'unknown')
            self.logger.info(f"[用户] {user_id}")
        
        # 不返回回复，仅记录
        return None


# ========== 便捷函数 ==========

def create_simple_handlers() -> list:
    """
    创建简单处理器列表
    
    Returns:
        处理器列表
    """
    return [
        SimpleReplyHandler(),
        TextOnlyHandler(),
        LoggingHandler()
    ]


def create_handler_by_name(name: str) -> Optional[BaseHandler]:
    """
    根据名称创建处理器
    
    Args:
        name: 处理器名称
        
    Returns:
        处理器实例
    """
    handlers = {
        "simple": SimpleReplyHandler,
        "text_only": TextOnlyHandler,
        "logging": LoggingHandler
    }
    
    handler_class = handlers.get(name.lower())
    if handler_class:
        return handler_class()
    
    return None
