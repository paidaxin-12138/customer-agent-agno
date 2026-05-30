"""
买家退换货/退款意向 → 按购买天数与明确意图发送 MMS 卡片或转人工。

策略见 utils/after_sales_policy.py；配置项 chat.after_sales_apply_*。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from bridge.context import ChannelType, Context, ContextType
from config import config

from .base import BaseHandler
from .order_logistics_handler import _extract_order_sn, _kw
from utils.after_sales_policy import (
    AFTER_SALES_REFUND_ONLY,
    AfterSalesAction,
    AfterSalesIntent,
    decide_after_sales,
    detect_after_sales_intent,
    is_after_sales_related,
)

# 已有进行中售后时不再重复发卡
_ACTIVE_AFTER_SALES = frozenset({2, 3, 4, 5, 7, 8, 14, 15, 16, 18, 21, 22, 27, 31, 32, 33})

_COOLDOWN: Dict[str, float] = {}

_HUMAN_NOTICE_DEFAULT = "稍等下，这边为您转接人工客服处理~"


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


def _is_after_sales_apply_quota_error(err: Optional[str]) -> bool:
    if not err:
        return False
    text = str(err)
    return "已达上限" in text or ("次数" in text and "上限" in text)


def _is_order_not_eligible_error(err: Optional[str]) -> bool:
    if not err:
        return False
    text = str(err)
    return "不能申请售后" in text or "无法申请售后" in text


def _return_refund_window_days() -> float:
    """已发货退货退款窗口（天，含边界）；可选 hours 覆盖。默认 7 天。"""
    raw_h = config.get("chat.after_sales_apply_return_refund_hours")
    if raw_h is not None and str(raw_h).strip() != "":
        return float(raw_h) / 24.0
    return float(config.get("chat.after_sales_apply_return_refund_days", 7) or 7)


def _fail_cooldown_sec(err: Optional[str]) -> int:
    """发卡失败后的冷却，避免买家每句话都再打 MMS。"""
    if _is_after_sales_apply_quota_error(err):
        return int(
            config.get("chat.after_sales_apply_quota_cooldown_sec", 86400) or 86400
        )
    return int(config.get("chat.after_sales_apply_fail_cooldown_sec", 300) or 300)


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


def _message_text(context: Context) -> str:
    if context.type == ContextType.TEXT and isinstance(context.content, str):
        return context.content.strip()
    if context.type == ContextType.ORDER_INFO and isinstance(context.content, dict):
        return str(context.content.get("goods_name") or "")
    return ""


def _human_notice_for_reason(reason: str) -> str:
    key_map = {
        "refund_only": "after_sales_apply_refund_only_human_notice",
        "unknown_purchase_time": "after_sales_apply_unknown_order_time_notice",
        "over_max_days": "after_sales_apply_over_90_human_notice",
        "mid_window_return_refund": "after_sales_apply_mid_window_human_notice",
        "unshipped_exchange": "after_sales_apply_unshipped_exchange_notice",
    }
    defaults = {
        "refund_only": (
            "亲，仅退款需要人工为您核实处理，这边马上为您转接人工客服~"
        ),
        "unknown_purchase_time": (
            "亲，暂未查到该订单的购买时间，为您转接人工客服协助处理退换货~"
        ),
        "over_max_days": (
            "亲，您的订单已超过可在线申请售后的期限，为您转接人工客服进一步处理~"
        ),
        "mid_window_return_refund": (
            "亲，您的订单已超过 7 天无理由退货退款期限，退货退款需人工为您办理，"
            "这边为您转接人工客服~"
        ),
        "unshipped_exchange": (
            "亲，您的订单尚未发货，换货需人工为您处理，这边为您转接人工客服~"
        ),
    }
    cfg_key = key_map.get(reason)
    if cfg_key:
        return str(
            config.get(f"chat.{cfg_key}")
            or defaults.get(reason, _HUMAN_NOTICE_DEFAULT)
        )
    return _HUMAN_NOTICE_DEFAULT


class AfterSalesApplyHandler(BaseHandler):
    """按购买天数与买家意图：发卡（退货退款/换货）或转人工。"""

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
        return is_after_sales_related(
            context.content if isinstance(context.content, str) else ""
        )

    async def handle(self, context: Context, metadata: Dict[str, Any]) -> bool:
        shop_id = metadata.get("shop_id") or _kw(context, "shop_id")
        user_id = metadata.get("user_id") or _kw(context, "user_id")
        from_uid = metadata.get("from_uid") or _kw(context, "from_uid")
        if not all([shop_id, user_id, from_uid]):
            return False

        text = _message_text(context)
        if context.type == ContextType.TEXT and not is_after_sales_related(text):
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
            if not is_after_sales_related(text):
                return False

        cooldown_sec = int(config.get("chat.after_sales_apply_cooldown_sec", 300) or 300)
        if _in_cooldown(str(shop_id), str(from_uid), cooldown_sec):
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
                if status == "no_eligible":
                    await self._send_text(
                        shop_id,
                        user_id,
                        from_uid,
                        config.get(
                            "chat.after_sales_apply_order_not_eligible_notice",
                            "亲，查到您的订单已完成退款或正在售后处理中，暂无法再次发送申请卡片；"
                            "如有疑问请回复「人工」为您处理~",
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
                    order_sn = await asyncio.to_thread(
                        api.pick_latest_order_sn, str(from_uid)
                    )
                    if order_sn:
                        _api_ok, buyer_orders = await asyncio.to_thread(
                            api.fetch_orders_by_buyer_uid, str(from_uid)
                        )
                        if not _api_ok:
                            buyer_orders = []
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

        intent = detect_after_sales_intent(text)
        days: Optional[float] = None
        order_rec: Optional[dict] = None
        try:
            from Channel.pinduoduo.utils.API.chat_orders import (
                days_since_purchase,
                find_order_by_sn,
            )

            order_rec = (
                find_order_by_sn(buyer_orders, order_sn) if buyer_orders else None
            )
            if order_rec:
                days = days_since_purchase(order_rec)
        except Exception as e:
            self.logger.debug(f"解析购买时间失败: {e}")

        from Channel.pinduoduo.utils.API.chat_orders import order_shipping_status

        ship_status: Optional[int] = None
        if order_rec:
            ship_status = order_shipping_status(order_rec)

        return_days = _return_refund_window_days()
        exchange_max_days = float(
            config.get("chat.after_sales_apply_exchange_max_days", 90) or 90
        )
        decision = decide_after_sales(
            days,
            intent,
            user_ship_status=ship_status,
            return_refund_days=return_days,
            exchange_max_days=exchange_max_days,
        )

        self.logger.info(
            f"售后策略 order_sn={order_sn} ship={ship_status} days={days} "
            f"intent={intent.value} action={decision.action.value} "
            f"type={decision.after_sales_type} reason={decision.reason}"
        )

        if decision.action == AfterSalesAction.TRANSFER_HUMAN:
            notice = _human_notice_for_reason(decision.reason)
            await self._transfer_to_human(
                context, metadata, shop_id, user_id, from_uid, notice
            )
            return True

        policy_type = decision.after_sales_type
        if policy_type in (None, AFTER_SALES_REFUND_ONLY):
            await self._transfer_to_human(
                context,
                metadata,
                shop_id,
                user_id,
                from_uid,
                _human_notice_for_reason("refund_only"),
            )
            return True

        refund_amount = int(
            config.get("chat.after_sales_apply_refund_amount_fen", 0) or 0
        )
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

        from utils.merchant_refund_apply_record import (
            RefundApplyGate,
            check_refund_apply_gate,
            gate_notice,
            save_failed_apply,
            save_pending_after_send,
        )

        gate = check_refund_apply_gate(str(shop_id), order_sn)
        if gate != RefundApplyGate.SEND:
            notice = gate_notice(gate)
            self.logger.info(
                f"跳过发卡 order_sn={order_sn} gate={gate.value} "
                f"（本地已有代申请记录）"
            )
            await self._send_text(shop_id, user_id, from_uid, notice)
            return True

        from Channel.pinduoduo.utils.API.chat_orders import build_ask_refund_apply_params

        card_params = build_ask_refund_apply_params(
            order_rec,
            int(policy_type or 3),
            refund_amount,
            default_shipped_question_type=int(
                config.get("chat.after_sales_apply_question_type", 1) or 1
            ),
            default_unshipped_question_type=int(
                config.get("chat.after_sales_apply_question_type_unshipped", 0)
                or 0
            ),
            card_message=config.get("chat.after_sales_apply_card_message"),
        )
        if card_params.refund_amount <= 0:
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

        if int(policy_type or 0) != card_params.after_sales_type:
            self.logger.info(
                f"未发货订单发卡类型调整: {policy_type} -> {card_params.after_sales_type} "
                f"order_sn={order_sn}"
            )

        self.logger.info(
            f"发卡参数 order_sn={order_sn} type={card_params.after_sales_type} "
            f"question_type={card_params.question_type} amount_fen={card_params.refund_amount} "
            f"ship={card_params.user_ship_status}"
        )

        result: Optional[dict] = None
        try:
            from Channel.pinduoduo.utils.API.send_message import SendMessage

            sender = SendMessage(str(shop_id), str(user_id))
            result = await asyncio.to_thread(
                sender.send_ask_refund_apply,
                order_sn,
                after_sales_type=card_params.after_sales_type,
                question_type=card_params.question_type,
                refund_amount=card_params.refund_amount,
                message=card_params.message or None,
                user_ship_status=card_params.user_ship_status,
            )
            ok = isinstance(result, dict) and result.get("success") is True
            if not ok and isinstance(result, dict):
                err = result.get("errorMsg") or result.get("error_msg")
                self.logger.error(
                    f"申请退换货卡片失败 order_sn={order_sn} "
                    f"type={card_params.after_sales_type} "
                    f"question_type={card_params.question_type} "
                    f"amount_fen={card_params.refund_amount} "
                    f"ship={card_params.user_ship_status}: {err}"
                )
        except Exception as e:
            self.logger.error(f"发送申请退换货卡片异常: {e}")
            ok = False

        if ok:
            record_id = save_pending_after_send(
                str(shop_id),
                str(from_uid),
                order_sn,
                after_sales_type=card_params.after_sales_type,
                refund_amount_fen=card_params.refund_amount,
            )
            self.logger.info(
                f"代申请已提交 pending order_sn={order_sn} record_id={record_id} "
                f"（待 type=19 补全 valid_time）"
            )
            _set_cooldown(str(shop_id), str(from_uid), cooldown_sec)
            from Message.handlers.channel_send import notify_outbound_from_metadata

            notify_outbound_from_metadata(context=context, metadata=metadata)
            # 跟发文案改在 type=19 下行确认卡片未过期后再发，避免「先教操作、卡却已过期」
        else:
            err_msg = None
            if isinstance(result, dict):
                err_msg = result.get("errorMsg") or result.get("error_msg")
            fail_cd = _fail_cooldown_sec(
                str(err_msg) if err_msg is not None else None
            )
            if fail_cd > 0:
                _set_cooldown(str(shop_id), str(from_uid), fail_cd)
            if _is_after_sales_apply_quota_error(
                str(err_msg) if err_msg is not None else None
            ):
                notice = config.get(
                    "chat.after_sales_apply_quota_notice",
                    "亲，该订单今日代申请售后次数已满，请您在订单详情页自行申请售后，"
                    "或回复「人工」为您处理~",
                )
            elif _is_order_not_eligible_error(
                str(err_msg) if err_msg is not None else None
            ):
                notice = config.get(
                    "chat.after_sales_apply_order_not_eligible_notice",
                    "亲，查到您的订单已完成退款或正在售后处理中，暂无法再次发送申请卡片；"
                    "如有疑问请回复「人工」为您处理~",
                )
            else:
                notice = config.get(
                    "chat.after_sales_apply_fail_notice",
                    "亲，退换货申请卡片发送未成功，请您在订单里点击「申请售后」，"
                    "或回复「人工」为您处理~",
                )
            save_failed_apply(
                str(shop_id),
                str(from_uid),
                order_sn,
                error_msg=str(err_msg) if err_msg is not None else None,
                after_sales_type=card_params.after_sales_type,
                refund_amount_fen=card_params.refund_amount,
            )
            await self._send_text(shop_id, user_id, from_uid, notice)
        return True

    async def _transfer_to_human(
        self,
        context: Context,
        metadata: Dict[str, Any],
        shop_id: Any,
        user_id: Any,
        from_uid: Any,
        notice: str,
    ) -> None:
        try:
            from core.human_assist_bus import emit_human_assist

            emit_human_assist(
                "after_sales_policy",
                context,
                metadata,
                _message_text(context),
            )
        except Exception as e:
            self.logger.debug(f"emit_human_assist: {e}")

        if notice:
            await self._send_text(shop_id, user_id, from_uid, notice, metadata)

        try:
            from Message.handlers.channel_send import transfer_to_available_cs_async

            await transfer_to_available_cs_async(shop_id, user_id, from_uid)
        except Exception as e:
            self.logger.debug(f"转接会话: {e}")

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
        ok = await self.send_text_to_buyer(
            shop_id, user_id, from_uid, reply, metadata=metadata
        )
        if not ok:
            self.logger.error("售后话术发送失败")
