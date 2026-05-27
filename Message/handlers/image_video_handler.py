"""
买家发送图片/视频：自动回复链路中的 LLM 无法看图，默认转人工并给买家清晰说明（不引导再发图）。
"""

from __future__ import annotations

import asyncio
from typing import Dict

from bridge.context import Context, ContextType
from config import config

from .base import BaseHandler

_DEFAULT_BUYER_NOTICE = (
    "亲亲，图片和视频需要人工客服打开才能看清，这边已经帮您备注给同事啦，"
    "稍后有人看图给您回复，您稍等一下～"
)


class ImageVideoHumanHandler(BaseHandler):
    """图片/视频 → 人工协助（与关键词转人工同一套弹窗与实时聊天）。"""

    def __init__(self):
        super().__init__("ImageVideoHumanHandler")

    def can_handle(self, context: Context) -> bool:
        if not bool(config.get("chat.image_video_forward_human", True)):
            return False
        return context.type in (ContextType.IMAGE, ContextType.VIDEO)

    def _buyer_notice(self) -> str:
        custom = (config.get("chat.image_video_buyer_notice") or "").strip()
        return custom if custom else _DEFAULT_BUYER_NOTICE

    def _build_question(self, context: Context) -> str:
        raw = context.content if isinstance(context.content, str) else str(context.content or "")
        raw = (raw or "").strip()
        if context.type == ContextType.VIDEO:
            label = "买家发送视频"
        else:
            label = "买家发送图片"
        if len(raw) > 800:
            raw = raw[:800] + "…"
        return f"{label}（链接/内容）：{raw}" if raw else label

    async def handle(self, context: Context, metadata: Dict[str, Any]) -> bool:
        shop_id = metadata.get("shop_id")
        user_id = metadata.get("user_id")
        from_uid = metadata.get("from_uid")
        if not all([shop_id, user_id, from_uid]):
            self.logger.warning("图片/视频转人工：缺少 shop_id/user_id/from_uid")
            return False

        q = self._build_question(context)
        try:
            from core.human_assist_bus import emit_human_assist

            emit_human_assist("media_human", context, metadata, q)
        except Exception as e:
            self.logger.debug(f"emit_human_assist(media_human) 跳过: {e}")

        try:
            from Channel.pinduoduo.utils.API.send_message import SendMessage

            sender = SendMessage(str(shop_id), str(user_id))
            result = await asyncio.to_thread(
                sender.send_text, str(from_uid), self._buyer_notice()
            )
            if isinstance(result, dict) and result.get("success"):
                from Message.handlers.ai_reply_watchdog import notify_outbound_reply

                notify_outbound_reply(context, metadata)
        except Exception as e:
            self.logger.error(f"图片/视频转人工后发送买家提示失败: {e}")

        await self.log_message(context, "图片/视频已转人工", q[:120])
        return True
