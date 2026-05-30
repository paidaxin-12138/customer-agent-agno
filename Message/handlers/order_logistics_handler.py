"""
物流咨询 → 调用开放平台 pdd.logistics.ordertrace.get（改址由 AddressChangeHandler 处理）。

文档：https://open.pinduoduo.com/application/document/api?id=pdd.logistics.ordertrace.get
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, Optional

from bridge.context import Context, ContextType, ChannelType
from config import config

from .base import BaseHandler


def _is_logistics_intent(text: str) -> bool:
    """询问包裹/物流进度（避免误伤闲聊）。"""
    t = (text or "").strip()
    if not t:
        return False
    strong = (
        "物流",
        "查物流",
        "快递到哪",
        "快递哪里",
        "快递呢",
        "发货了吗",
        "发货没",
        "发了吗",
        "揽收",
        "派送",
        "派件",
        "轨迹",
        "运单号",
        "运单",
        "到哪了",
        "到哪里了",
        "几天到",
        "什么时候到",
        "啥时候到",
    )
    if any(s in t for s in strong):
        return True
    if "快递" in t and any(x in t for x in ("哪", "查", "单", "多久", "几天")):
        return True
    return False


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

    def __init__(self):
        super().__init__("OrderLogisticsHandler")

    def can_handle(self, context: Context) -> bool:
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

        if not config.get("pinduoduo_open.enabled", True):
            await self._send_reply(
                shop_id,
                user_id,
                from_uid,
                "亲，物流查询未开启；如需查件请先联系店主配置开放平台，或为您转人工处理。",
            )
            return True

        order_sn = _extract_order_sn(text)
        if not order_sn:
            await self._send_reply(
                shop_id,
                user_id,
                from_uid,
                "亲，麻烦发一下拼多多订单号（订单详情页可复制，格式类似 250105-xxxxxxxx），"
                "我这边帮您查物流进度~",
            )
            return True

        try:
            from Channel.pinduoduo.utils.API.logistics import (
                LogisticsManager,
                format_order_trace_reply,
            )

            mgr = LogisticsManager(str(shop_id), str(user_id))
            raw = await asyncio.to_thread(mgr.get_order_trace, order_sn)
            reply = format_order_trace_reply(order_sn, raw)
            await self._send_reply(shop_id, user_id, from_uid, reply)
        except Exception as e:
            self.logger.error(f"物流查询失败: {e}")
            await self._send_reply(
                shop_id,
                user_id,
                from_uid,
                "亲，物流查询遇到一点问题，请稍后再试或联系人工客服帮您查单。",
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
