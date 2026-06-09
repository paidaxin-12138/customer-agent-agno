# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
处理器基类和通用工具
"""
from typing import ClassVar, Dict, Any, Optional, FrozenSet
from utils.logger_loguru import get_logger
from bridge.context import Context
from ..core.handlers import MessageHandler


class BaseHandler(MessageHandler):
    """处理器基类，提供通用功能"""

    allowed_stages: ClassVar[FrozenSet[str]] = frozenset({"idle"})

    def __init__(self, name: Optional[str] = None):
        super().__init__()
        self.name = name or self.__class__.__name__

    def _stage_allowed(self, context: Context) -> bool:
        from Message.core.handlers import stage_allowed_for_context

        return stage_allowed_for_context(context, self.allowed_stages)

    def can_handle(self, context: Context) -> bool:
        if not self._stage_allowed(context):
            return False
        return self._can_handle_impl(context)

    def _can_handle_impl(self, context: Context) -> bool:
        return False

    async def log_message(self, context: Context, action: str, extra_info: str = ""):
        """统一的日志记录"""
        user_info = self._get_user_info(context)
        self.logger.info(f"{self.name} {action} - {user_info} - {context.content}... {extra_info}")

    def _get_user_info(self, context: Context) -> str:
        """提取用户信息"""
        try:
            if hasattr(context, 'kwargs') and context.kwargs:
                from_uid = getattr(context.kwargs, 'from_uid', None)
                username = getattr(context.kwargs, 'username', None)
                if username:
                    return f"用户:{username}({from_uid})"
                elif from_uid:
                    return f"用户:{from_uid}"
            return "用户:unknown"
        except Exception as e:
            self.logger.debug("_get_user_info: {}", e)
            return "用户:unknown"

    async def send_text_to_buyer(
        self,
        shop_id: Any,
        user_id: Any,
        from_uid: Any,
        text: str,
        *,
        context: Optional[Context] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        from .channel_send import send_text_to_buyer

        ok = await send_text_to_buyer(
            shop_id,
            user_id,
            from_uid,
            text,
            context=context,
            metadata=metadata,
        )
        if ok and context is not None and metadata is not None:
            try:
                from Agent.CustomerAgent.conversation_memory import (
                    append_handler_turn_summary,
                    resolve_session_id,
                )

                sid = resolve_session_id(context, metadata)
                if sid is not None:
                    buyer = context.content if isinstance(context.content, str) else str(
                        context.content or ""
                    )
                    append_handler_turn_summary(
                        sid, buyer_text=buyer, agent_text=text
                    )
            except Exception as e:
                self.logger.debug("append_handler_turn_summary: {}", e)
        return ok
