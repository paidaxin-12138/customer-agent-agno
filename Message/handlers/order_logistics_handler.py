"""
物流咨询 → 优先 MMS userAllOrder（traceInfoList / 订单状态），开放平台轨迹为可选降级。

改址由 AddressChangeHandler 处理。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, Optional

from bridge.context import Context, ContextType, ChannelType

from utils.logistics_intent import is_logistics_intent

from .base import BaseHandler


def _is_logistics_intent(text: str) -> bool:
    """向后兼容别名。"""
    return is_logistics_intent(text)


def _kw(context: Context, key: str) -> Any:
    k = getattr(context, "kwargs", None)
    if k is None:
        return None
    if isinstance(k, dict):
        return k.get(key)
    return getattr(k, key, None)


def _extract_order_sn(text: str) -> Optional[str]:
    """从文本中提取拼多多订单号（常见格式 yyMMdd-数字）。"""
    s = (text or "").strip()
    if not s:
        return None
    m = re.search(r"(?:订单号|订单编号|单号)[:：\s]*(\d{6}-\d+)", s)
    if m:
        return m.group(1).strip()
    for pat in (r"\b(\d{6}-\d{15,24})\b", r"\b(\d{8}-\d{15,24})\b"):
        m2 = re.search(pat, s)
        if m2:
            return m2.group(1).strip()
    return None


class OrderLogisticsHandler(BaseHandler):
    """物流咨询查轨迹。"""

    allowed_stages = frozenset({"idle", "logistics"})

    def __init__(self):
        super().__init__("OrderLogisticsHandler")

    @staticmethod
    def _commit_logistics_state(
        context: Context,
        metadata: Dict[str, Any],
        *,
        order_sn: Optional[str] = None,
        release_stage: bool = False,
    ) -> None:
        from Agent.CustomerAgent.conversation_memory import (
            commit_handler_session_from_context,
        )

        slots: Dict[str, str] = {}
        if order_sn:
            slots["order_sn"] = order_sn
        commit_handler_session_from_context(
            context,
            metadata,
            stage="logistics",
            intent="logistics",
            slots=slots or None,
            source_handler="OrderLogisticsHandler",
            release_stage=release_stage,
        )

    def _can_handle_impl(self, context: Context) -> bool:
        if context.type != ContextType.TEXT:
            return False
        ch = context.channel_type
        if ch is not None and ch != ChannelType.PINDUODUO:
            return False
        text = context.content if isinstance(context.content, str) else ""
        text = (text or "").strip()
        if not text:
            return False
        return _is_logistics_intent(text)

    async def handle(self, context: Context, metadata: Dict[str, Any]) -> bool:
        text = context.content if isinstance(context.content, str) else ""
        text = (text or "").strip()

        shop_id = metadata.get("shop_id") or _kw(context, "shop_id")
        user_id = metadata.get("user_id") or _kw(context, "user_id")
        from_uid = metadata.get("from_uid") or _kw(context, "from_uid")

        if not all([shop_id, user_id, from_uid]):
            return False

        if not _is_logistics_intent(text):
            return False

        order_sn = _extract_order_sn(text)

        try:
            from Channel.pinduoduo.utils.API.logistics import lookup_order_logistics_reply

            reply, resolved_sn, need_pick = await asyncio.to_thread(
                lookup_order_logistics_reply,
                str(shop_id),
                str(user_id),
                str(from_uid),
                order_sn,
            )
            await self._send_reply(shop_id, user_id, from_uid, reply)
        except Exception as e:
            self.logger.error(f"物流查询失败: {e}")
            await self._send_reply(
                shop_id,
                user_id,
                from_uid,
                "亲，物流查询遇到一点问题，请稍后再试或联系人工客服帮您查单。",
            )
            self._commit_logistics_state(context, metadata, release_stage=True)
            return True

        self._commit_logistics_state(
            context,
            metadata,
            order_sn=resolved_sn or order_sn,
            release_stage=not need_pick,
        )
        return True

    async def _send_reply(
        self,
        shop_id: Any,
        user_id: Any,
        from_uid: Any,
        reply: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        ok = await self.send_text_to_buyer(
            shop_id, user_id, from_uid, reply, metadata=metadata
        )
        if not ok:
            self.logger.error("物流话术发送失败")
