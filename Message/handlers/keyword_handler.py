# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
关键词检测处理器 - 检测转人工关键词并触发转人工流程
"""
from typing import Dict, Any, FrozenSet
from bridge.context import Context, ContextType
from config import config
from .base import BaseHandler
from core.session_stages import ALL_HANDLER_STAGES
from .channel_send import send_text_to_buyer, transfer_to_available_cs_async
from database.db_manager import db_manager
from utils.human_transfer_intent import detect_human_transfer_intent
from utils.human_escalation_comfort import (
    resolve_session_ids,
    send_human_transfer_comfort,
)
from utils.logger_loguru import get_logger

_DEFAULT_KEYWORDS = frozenset(
    {
        "转人工", "人工客服", "真人", "客服", "人工", "工单", "好评",
        "取消订单", "改地址", "转售后客服", "转售后", "返现", "过敏",
        "退款", "没有效果", "骗人", "投诉", "纠纷", "开发票", "开票",
        "烂", "取消", "备注",
    }
)


class KeywordDetectionHandler(BaseHandler):
    """关键词检测处理器 - 检测转人工关键词并触发转人工流程"""

    allowed_stages = ALL_HANDLER_STAGES

    _LOCAL_HUMAN_ASSIST_PHRASES = (
        "转人工",
        "人工客服",
        "真人客服",
        "真人",
        "我要人工",
        "找人工",
        "接人工",
    )
    _HUMAN_TRANSFER_NOTICE = "稍等下 这边上报一下呢亲亲"  # 兼容旧引用；实际文案见 chat.human_transfer_notice

    def __init__(self):
        super().__init__("KeywordDetectionHandler")
        self.logger = get_logger("KeywordDetectionHandler")
        self._keywords_snapshot: FrozenSet[str] = self._load_keywords_frozen()
        self.logger.info(
            f"关键词检测处理器初始化完成，加载了 {len(self._keywords_snapshot)} 个关键词"
        )

    def _load_keywords_frozen(self) -> FrozenSet[str]:
        try:
            keywords_data = db_manager.get_all_keywords()
            return frozenset(
                item["keyword"].lower()
                for item in keywords_data
                if item.get("keyword")
            )
        except Exception as e:
            self.logger.error(f"加载关键词失败: {e}")
            self.logger.warning("使用默认关键词集")
            return _DEFAULT_KEYWORDS

    @property
    def keywords(self) -> FrozenSet[str]:
        """只读视图（兼容 get_keywords）。"""
        return self._keywords_snapshot

    def _can_handle_impl(self, context: Context) -> bool:
        if context.type != ContextType.TEXT:
            return False
        if not context.content or not isinstance(context.content, str):
            return False
        snapshot = self._keywords_snapshot
        if self._semantic_human_transfer_enabled() and detect_human_transfer_intent(
            context.content
        ):
            self.logger.debug(f"检测到转人工语义: '{context.content}'")
            return True
        content_lower = context.content.lower()
        for keyword in snapshot:
            if keyword in content_lower:
                self.logger.debug(f"检测到关键词: '{keyword}' 在消息: '{context.content}'")
                return True
        return False

    @staticmethod
    def _semantic_human_transfer_enabled() -> bool:
        return bool(config.get("chat.human_transfer_semantic_enabled", True))

    def _wants_local_human_assist(self, content: str) -> bool:
        c = (content or "").strip().lower()
        return any(p.lower() in c for p in self._LOCAL_HUMAN_ASSIST_PHRASES)

    def _buyer_wants_explicit_human(self, content: str) -> bool:
        if self._semantic_human_transfer_enabled() and detect_human_transfer_intent(
            content
        ):
            return True
        return self._wants_local_human_assist(content)

    async def handle(self, context: Context, metadata: Dict[str, Any]) -> bool:
        """关键词命中：代码转接 + 固定安抚，不经过 LLM。"""
        try:
            shop_id, user_id, from_uid = resolve_session_ids(context, metadata)
            content = (
                context.content
                if context.type == ContextType.TEXT and isinstance(context.content, str)
                else ""
            )

            await send_human_transfer_comfort(
                context, metadata, reason="keyword_human"
            )
            try:
                from core.human_assist_bus import emit_human_assist

                emit_human_assist(
                    "keyword_human",
                    context,
                    metadata,
                    content,
                )
            except Exception as e:
                self.logger.debug(f"emit_human_assist 跳过: {e}")

            if not all([shop_id, user_id, from_uid]):
                metadata["_handler_resolved_without_outbound"] = True
                return True

            try:
                from utils.session_human_lock import lock_session_to_human

                lock_session_to_human(
                    context=context,
                    metadata=metadata,
                    reason="keyword_human",
                )
            except Exception as e:
                self.logger.debug(f"keyword lock human: {e}")

            if await transfer_to_available_cs_async(
                shop_id, user_id, from_uid, context=context, metadata=metadata
            ):
                self.logger.info("关键词命中，会话已代码转接")
            elif self._buyer_wants_explicit_human(content):
                await send_text_to_buyer(
                    shop_id,
                    user_id,
                    from_uid,
                    "抱歉，当前没有其他客服在线，请您稍后再试。",
                    context=context,
                    metadata=metadata,
                )

            if metadata.get("_outbound_comfort_sent"):
                metadata["_handler_resolved_without_outbound"] = True
            return True

        except Exception as e:
            self.logger.error(f"客服转接处理失败: {e}")
            return False

    def reload_keywords(self) -> None:
        """Copy-on-write：原子替换快照，热加载期间 can_handle 读旧集或新集。"""
        old_count = len(self._keywords_snapshot)
        new_snapshot = self._load_keywords_frozen()
        self._keywords_snapshot = new_snapshot
        self.logger.info(
            f"关键词重新加载完成: {old_count} -> {len(new_snapshot)} (cow)"
        )

    def get_keyword_count(self) -> int:
        return len(self._keywords_snapshot)

    def get_keywords(self) -> FrozenSet[str]:
        return self._keywords_snapshot
