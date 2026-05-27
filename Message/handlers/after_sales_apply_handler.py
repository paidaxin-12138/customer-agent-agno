"""
买家退换货/退款意向 → 发送 MMS「申请退换货」卡片。

需在商家后台验证 ask_refund_apply/send 参数；类型枚举见 config chat.after_sales_apply_*。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from bridge.context import ChannelType, Context, ContextType
from config import config

from .base import BaseHandler
from .order_logistics_handler import _extract_order_sn, _kw

# 命中后优先发卡（在关键词「退款」转人工之前）
_REFUND_INTENT_PHRASES = (
    "退货",
    "退换货",
    "退换",
    "换货",
    "申请退款",
    "申请退货",
    "怎么退",
    "如何退",
    "想退",
    "要退",
    "退款",
    "退钱",
    "不想要了",
    "拒收",
    "申请售后",
    "售后申请",
    "能退吗",
    "可以退吗",
    "能不能退",
)

# 已有进行中售后时不再重复发卡
_ACTIVE_AFTER_SALES = frozenset({2, 3, 4, 5, 7, 8, 14, 15, 16, 18, 21, 22, 27, 31, 32, 33})

_COOLDOWN: Dict[str, float] = {}


def _is_refund_intent(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return any(p in t for p in _REFUND_INTENT_PHRASES)


def _cooldown_key(shop_id: str, from_uid: str) -> str:
    return f"{shop_id}:{from_uid}"


def _in_cooldown(shop_id: str, from_uid: str, cooldown_sec: int) -> bool:
    if cooldown_sec <= 0:
        return False
    until = _COOLDOWN.get(_cooldown_key(shop_id, from_uid))
    return until is not None and time.time() < until


def _set_cooldown(shop_id: str, from_uid: str, cooldown_sec: int) -> None:
    if cooldown_sec > 0:
        _COOLDOWN[_cooldown_key(shop_id, from_uid)] = time.time() + cooldown_sec


def _order_sn_from_order_info(content: Any) -> Optional[str]:
    if isinstance(content, dict):
        oid = content.get("order_id") or content.get("order_sn")
        if oid:
            return str(oid).strip()
    if isinstance(content, str) and content.strip():
        return content.strip()
    return None


def _after_sales_status_from_context(context: Context) -> Optional[int]:
    content = context.content
    if isinstance(content, dict):
        raw = content.get("afterSalesStatus")
        if raw is not None:
            try:
                return int(raw)
            except (TypeError, ValueError):
                return None
    return None


class AfterSalesApplyHandler(BaseHandler):
    """检测退换货意向并向买家推送申请售后卡片。"""

    def __init__(self):
        super().__init__("AfterSalesApplyHandler")

    def can_handle(self, context: Context) -> bool:
        if not config.get("chat.after_sales_apply_enabled", True):
            return False
        ch = context.channel_type
        if ch is not None and ch != ChannelType.PINDUODUO:
            return False

        if context.type == ContextType.ORDER_INFO:
            return True

        if context.type != ContextType.TEXT:
            return False
        text = context.content if isinstance(context.content, str) else ""
        return _is_refund_intent(text)

    async def handle(self, context: Context, metadata: Dict[str, Any]) -> bool:
        shop_id = metadata.get("shop_id") or _kw(context, "shop_id")
        user_id = metadata.get("user_id") or _kw(context, "user_id")
        from_uid = metadata.get("from_uid") or _kw(context, "from_uid")
        if not all([shop_id, user_id, from_uid]):
            return False

        from utils.session_order_cache import get_recent_order, remember_order

        ttl = int(config.get("chat.after_sales_apply_order_cache_ttl_sec", 3600) or 3600)

        if context.type == ContextType.ORDER_INFO:
            order_sn = _order_sn_from_order_info(context.content)
            if order_sn:
                remember_order(str(shop_id), str(from_uid), order_sn, ttl_sec=ttl)
            status = _after_sales_status_from_context(context)
            if status is not None and status in _ACTIVE_AFTER_SALES:
                await self._send_text(
                    shop_id,
                    user_id,
                    from_uid,
                    config.get(
                        "chat.after_sales_apply_already_in_progress_notice",
                        "亲，看到您这笔订单已在售后处理中，请在订单详情查看进度；有疑问可回复「人工」。",
                    ),
                )
                return True
            if not _is_refund_intent(
                context.content.get("goods_name", "") if isinstance(context.content, dict) else ""
            ):
                return False

        text = ""
        if context.type == ContextType.TEXT and isinstance(context.content, str):
            text = context.content.strip()
            if not _is_refund_intent(text):
                return False

        cooldown_sec = int(config.get("chat.after_sales_apply_cooldown_sec", 300) or 300)
        if _in_cooldown(str(shop_id), str(from_uid), cooldown_sec):
            # 冷却期内不重复发卡，交给后续 AI/关键词处理
            return False

        preferred_sn = _extract_order_sn(text) or get_recent_order(str(shop_id), str(from_uid))
        buyer_orders: list = []
        order_sn: Optional[str] = None

        if config.get("chat.after_sales_apply_check_orders_by_uid", True):
            try:
                from Channel.pinduoduo.utils.API.chat_orders import ChatOrdersAPI

                api = ChatOrdersAPI(str(shop_id), str(user_id))
                status, resolved_sn, buyer_orders = await asyncio.to_thread(
                    api.resolve_order_for_buyer,
                    str(from_uid),
                    preferred_sn,
                )
                if status == "api_error":
                    await self._send_text(
                        shop_id,
                        user_id,
                        from_uid,
                        config.get(
                            "chat.after_sales_apply_orders_query_fail_notice",
                            "亲，订单查询暂时失败，请稍后再试或回复「人工」协助处理~",
                        ),
                    )
                    return True
                if status == "no_orders":
                    await self._send_text(
                        shop_id,
                        user_id,
                        from_uid,
                        config.get(
                            "chat.after_sales_apply_no_orders_notice",
                            "亲，暂未查到您在本店的订单记录，请确认是否用下单账号咨询，"
                            "或从订单页进入客服后再申请售后~",
                        ),
                    )
                    return True
                order_sn = resolved_sn
            except Exception as e:
                self.logger.error(f"按买家 UID 查询订单失败: {e}")
                await self._send_text(
                    shop_id,
                    user_id,
                    from_uid,
                    config.get(
                        "chat.after_sales_apply_orders_query_fail_notice",
                        "亲，订单查询暂时失败，请稍后再试或回复「人工」协助处理~",
                    ),
                )
                return True
        else:
            order_sn = preferred_sn
            if not order_sn:
                try:
                    from Channel.pinduoduo.utils.API.chat_orders import ChatOrdersAPI

                    api = ChatOrdersAPI(str(shop_id), str(user_id))
                    order_sn = await asyncio.to_thread(api.pick_latest_order_sn, str(from_uid))
                except Exception as e:
                    self.logger.debug(f"拉取买家订单失败: {e}")

        if not order_sn:
            await self._send_text(
                shop_id,
                user_id,
                from_uid,
                config.get(
                    "chat.after_sales_apply_need_order_notice",
                    "亲，麻烦发一下订单号（订单详情可复制，格式类似 250105-xxxxxxxx），"
                    "或从订单页进聊天发订单卡片，我这边给您发退换货申请~",
                ),
            )
            return True

        remember_order(str(shop_id), str(from_uid), order_sn, ttl_sec=ttl)

        after_sales_type = int(config.get("chat.after_sales_apply_after_sales_type", 3) or 3)
        question_type = int(config.get("chat.after_sales_apply_question_type", 1) or 1)
        refund_amount = int(config.get("chat.after_sales_apply_refund_amount_fen", 0) or 0)

        if refund_amount <= 0:
            try:
                from Channel.pinduoduo.utils.API.chat_orders import ChatOrdersAPI

                api = ChatOrdersAPI(str(shop_id), str(user_id))
                resolved = await asyncio.to_thread(
                    api.pick_refund_amount_fen,
                    str(from_uid),
                    order_sn,
                    buyer_orders if buyer_orders else None,
                )
                if resolved and resolved > 0:
                    refund_amount = resolved
            except Exception as e:
                self.logger.debug(f"解析订单金额失败: {e}")

        if refund_amount <= 0:
            await self._send_text(
                shop_id,
                user_id,
                from_uid,
                config.get(
                    "chat.after_sales_apply_amount_unknown_notice",
                    "亲，暂未获取到订单金额，请您在订单详情页直接申请售后，或回复「人工」协助处理~",
                ),
            )
            return True

        card_message = config.get("chat.after_sales_apply_card_message") or None
        follow_text = config.get("chat.after_sales_apply_follow_text") or ""

        try:
            from Channel.pinduoduo.utils.API.send_message import SendMessage

            sender = SendMessage(str(shop_id), str(user_id))
            result = await asyncio.to_thread(
                sender.send_ask_refund_apply,
                order_sn,
                after_sales_type=after_sales_type,
                question_type=question_type,
                refund_amount=refund_amount,
                message=card_message,
            )
            ok = isinstance(result, dict) and result.get("success") is True
        except Exception as e:
            self.logger.error(f"发送申请退换货卡片异常: {e}")
            ok = False

        if ok:
            _set_cooldown(str(shop_id), str(from_uid), cooldown_sec)
            from Message.handlers.ai_reply_watchdog import notify_outbound_reply

            notify_outbound_reply(metadata=metadata)
            if follow_text:
                await self._send_text(shop_id, user_id, from_uid, str(follow_text), metadata)
        else:
            await self._send_text(
                shop_id,
                user_id,
                from_uid,
                config.get(
                    "chat.after_sales_apply_fail_notice",
                    "亲，退换货申请卡片发送未成功，请您在订单里点击「申请售后」，或回复「人工」为您处理~",
                ),
            )
        return True

    async def _send_text(
        self,
        shop_id: Any,
        user_id: Any,
        from_uid: Any,
        reply: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not reply:
            return
        meta = metadata or {
            "shop_id": str(shop_id),
            "user_id": str(user_id),
            "from_uid": str(from_uid),
            "channel_name": "pinduoduo",
        }
        try:
            from Channel.pinduoduo.utils.API.send_message import SendMessage

            sender = SendMessage(str(shop_id), str(user_id))
            result = await asyncio.to_thread(sender.send_text, str(from_uid), reply)
            if isinstance(result, dict) and result.get("success"):
                from Message.handlers.ai_reply_watchdog import notify_outbound_reply

                notify_outbound_reply(metadata=meta)
        except Exception as e:
            self.logger.error(f"发送失败: {e}")
