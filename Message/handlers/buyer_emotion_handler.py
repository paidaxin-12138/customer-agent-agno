# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
买家情绪波动检测：首次弹窗预警；累计达到阈值后转人工（与关键词转人工一致）。
"""
from __future__ import annotations

from typing import Any, Dict

from bridge.context import Context, ContextType
from config import config

from utils.buyer_emotion_intent import (
    build_emotion_alert_summary,
    detect_buyer_emotion,
)
from utils.buyer_emotion_tracker import record_emotion_alert
from utils.human_escalation_comfort import (
    resolve_session_ids,
    send_human_transfer_comfort,
)

from .base import BaseHandler
from core.session_stages import ALL_HANDLER_STAGES
from .channel_send import transfer_to_available_cs_async
from .order_logistics_handler import _kw


class BuyerEmotionHandler(BaseHandler):
    """买家负面情绪 / 催促 / 投诉 → 人工预警或转人工。"""

    allowed_stages = ALL_HANDLER_STAGES

    def __init__(self):
        super().__init__("BuyerEmotionHandler")

    def _can_handle_impl(self, context: Context) -> bool:
        if not bool(config.get("chat.buyer_emotion_alert_enabled", True)):
            return False
        if context.type != ContextType.TEXT:
            return False
        text = context.content if isinstance(context.content, str) else ""
        return detect_buyer_emotion((text or "").strip())

    async def handle(self, context: Context, metadata: Dict[str, Any]) -> bool:
        text = context.content if isinstance(context.content, str) else ""
        text = (text or "").strip()
        if not text:
            return False

        try:
            from Message.handlers.ai_reply_watchdog import resolve_session_key

            session_key = resolve_session_key(context, metadata) or ""
        except Exception:
            session_key = ""

        threshold = int(config.get("chat.buyer_emotion_escalate_threshold", 2) or 2)
        threshold = max(1, min(threshold, 5))
        count = record_emotion_alert(session_key)
        nick = str(
            metadata.get("username")
            or _kw(context, "nickname")
            or metadata.get("from_uid")
            or "买家"
        )
        summary = build_emotion_alert_summary(text, buyer_nickname=nick)

        shop_id, user_id, from_uid = resolve_session_ids(context, metadata)

        if count >= threshold:
            await send_human_transfer_comfort(
                context, metadata, reason="buyer_emotion_escalate"
            )
            try:
                from core.human_assist_bus import emit_human_assist

                emit_human_assist(
                    "buyer_emotion_escalate",
                    context,
                    metadata,
                    summary,
                    extra={"emotion_alert_count": count},
                )
            except Exception as e:
                self.logger.debug(f"emit_human_assist(buyer_emotion_escalate): {e}")

            if all([shop_id, user_id, from_uid]):
                if await transfer_to_available_cs_async(
                    shop_id, user_id, from_uid, context=context, metadata=metadata
                ):
                    self.logger.info("情绪波动达阈值，会话已转接")
                    return True
            await self.log_message(
                context,
                "情绪波动转人工",
                f"count={count} text={text[:80]}",
            )
            if metadata.get("_outbound_comfort_sent"):
                metadata["_handler_resolved_without_outbound"] = True
            return True

        try:
            from core.human_assist_bus import emit_human_assist

            emit_human_assist(
                "buyer_emotion_alert",
                context,
                metadata,
                summary,
                extra={"emotion_alert_count": count},
            )
        except Exception as e:
            self.logger.debug(f"emit_human_assist(buyer_emotion_alert): {e}")

        await self.log_message(
            context,
            "情绪波动预警",
            f"count={count}/{threshold} text={text[:80]}",
        )
        # 未达转人工阈值：仅弹窗预警，不阻断 AI / 后续 Handler
        return False
