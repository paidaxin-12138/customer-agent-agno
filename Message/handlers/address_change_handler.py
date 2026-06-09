# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
买家改收货地址 → 解析地址 / 查单 / 话术 / 弹窗确认（MMS 改址由店主点确认后执行）。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from bridge.context import ChannelType, Context, ContextType
from config import config

from utils.address_parse import (
    AddressParseLevel,
    address_parse_level,
    is_address_change_intent,
    parse_address_from_text,
)
from utils.address_change_policy import pick_order_for_address_change

from .base import BaseHandler
from .order_logistics_handler import _kw

_CONFIRM_MARKERS = ("确认改址", "确认", "同意", "好的", "可以", "确定", "行")
_CANCEL_MARKERS = ("取消", "不要改", "不改了", "算了", "不用改", "放弃")


def _is_address_confirm_message(text: str) -> bool:
    t = (text or "").strip()
    if not t or _is_address_cancel_message(t):
        return False
    return any(m in t for m in _CONFIRM_MARKERS)


def _is_address_cancel_message(text: str) -> bool:
    t = (text or "").strip()
    return any(m in t for m in _CANCEL_MARKERS)


def _audit_address_change(
    *,
    order_sn: str,
    detail: str,
    success: bool,
    from_uid: str = "",
    shop_id: str = "",
) -> None:
    try:
        from utils.audit_log import audit_log

        audit_log(
            "address_change",
            order_sn or from_uid or "unknown",
            detail,
            operator="buyer",
            severity="info" if success else "warn",
            extra={
                "shop_id": shop_id,
                "buyer_uid": from_uid,
                "success": success,
                "order_sn": order_sn or None,
            },
        )
    except Exception as e:
        from utils.logger_loguru import get_logger

        get_logger("AddressChangeHandler").debug("address_change 审计写入失败: {}", e)


def _cfg(key: str, default: str) -> str:
    return str(config.get(f"chat.{key}", default) or default)


class AddressChangeHandler(BaseHandler):
    """改址专用处理器（查物流仍由 OrderLogisticsHandler 处理）。"""

    allowed_stages = frozenset({"idle", "address_change", "await_confirm"})

    def __init__(self):
        super().__init__("AddressChangeHandler")

    def _finish(
        self,
        context: Context,
        metadata: Dict[str, Any],
        *,
        parsed: Any = None,
        order_sn: str = "",
        stage: str = "address_change",
        release_stage: bool = False,
    ) -> bool:
        from Agent.CustomerAgent.conversation_memory import (
            commit_handler_session_from_context,
        )

        slots: Dict[str, str] = {}
        if order_sn:
            slots["order_sn"] = order_sn
        if parsed is not None:
            for key, val in (
                ("name", getattr(parsed, "name", None)),
                ("phone", getattr(parsed, "mobile", None)),
                ("province", getattr(parsed, "province", None)),
                ("city", getattr(parsed, "city", None)),
                ("district", getattr(parsed, "district", None)),
                ("address", getattr(parsed, "detail", None) or getattr(parsed, "full_text", None)),
            ):
                if val:
                    slots[key] = str(val)
        commit_handler_session_from_context(
            context,
            metadata,
            stage=stage,
            intent="address_change",
            slots=slots or None,
            source_handler="AddressChangeHandler",
            release_stage=release_stage,
        )
        return True

    def _can_handle_impl(self, context: Context) -> bool:
        if not config.get("chat.address_change_enabled", True):
            return False
        if context.type != ContextType.TEXT:
            return False
        ch = context.channel_type
        if ch is not None and ch != ChannelType.PINDUODUO:
            return False
        text = context.content if isinstance(context.content, str) else ""
        text = (text or "").strip()
        from Agent.CustomerAgent.conversation_memory import get_current_stage

        stage = get_current_stage(context)
        if stage == "await_confirm":
            return _is_address_confirm_message(text) or _is_address_cancel_message(text) or is_address_change_intent(text)
        return is_address_change_intent(text)

    async def handle(self, context: Context, metadata: Dict[str, Any]) -> bool:
        text = context.content if isinstance(context.content, str) else ""
        text = (text or "").strip()

        shop_id = metadata.get("shop_id") or _kw(context, "shop_id")
        user_id = metadata.get("user_id") or _kw(context, "user_id")
        from_uid = metadata.get("from_uid") or _kw(context, "from_uid")
        if not all([shop_id, user_id, from_uid]):
            return False

        from Agent.CustomerAgent.conversation_memory import get_current_stage

        if get_current_stage(context, metadata) == "await_confirm":
            if _is_address_cancel_message(text):
                await self._send_reply(
                    shop_id,
                    user_id,
                    from_uid,
                    _cfg(
                        "address_change_cancel_text",
                        "好的亲，已取消本次改址操作，如需修改可重新发送新地址~",
                    ),
                    metadata,
                )
                return self._finish(context, metadata, release_stage=True)
            if _is_address_confirm_message(text):
                await self._send_reply(
                    shop_id,
                    user_id,
                    from_uid,
                    _cfg(
                        "address_change_success_text",
                        "亲，已收到您的确认，店主会在后台为您处理改址，请留意物流更新~",
                    ),
                    metadata,
                )
                return self._finish(context, metadata, release_stage=True)

        parsed = parse_address_from_text(text)
        level = address_parse_level(parsed)

        if level == AddressParseLevel.NONE:
            await self._send_reply(
                shop_id,
                user_id,
                from_uid,
                _cfg(
                    "address_change_ask_full_address_text",
                    "亲，请提供完整的收货地址（省市区街道门牌号+收件人+电话），我会帮您尝试修改。",
                ),
                metadata,
            )
            return self._finish(context, metadata, parsed=parsed, stage="address_change")

        if level == AddressParseLevel.PARTIAL:
            await self._send_reply(
                shop_id,
                user_id,
                from_uid,
                _cfg(
                    "address_change_ask_complete_text",
                    "亲，您提供的地址好像不完整（缺少省/市/区），请重新提供完整地址，以免发错哦。",
                ),
                metadata,
            )
            return self._finish(context, metadata, parsed=parsed, stage="address_change")

        try:
            from Channel.pinduoduo.utils.API.chat_orders import ChatOrdersAPI

            api = ChatOrdersAPI(str(shop_id), str(user_id))
            ok, orders = await asyncio.to_thread(
                api.fetch_orders_by_buyer_uid, str(from_uid), 10
            )
        except Exception as e:
            self.logger.error(f"改址查单失败: {e}")
            ok, orders = False, []
            _audit_address_change(
                order_sn="",
                detail=f"改址查单失败: {e}",
                success=False,
                from_uid=str(from_uid),
                shop_id=str(shop_id),
            )

        if not ok:
            await self._send_reply(
                shop_id,
                user_id,
                from_uid,
                _cfg(
                    "after_sales_apply_orders_query_fail_notice",
                    "亲，订单查询暂时失败，请稍后再试或回复「人工」协助处理~",
                ),
                metadata,
            )
            return self._finish(context, metadata, parsed=parsed, release_stage=True)

        brief, pick_status = pick_order_for_address_change(orders, text, parsed)

        if pick_status == "no_orders":
            await self._send_reply(
                shop_id,
                user_id,
                from_uid,
                _cfg(
                    "address_change_no_orders_text",
                    "亲，暂未查到与您账号关联的本店订单，请确认是否用下单账号咨询，或提供订单号~",
                ),
                metadata,
            )
            return self._finish(context, metadata, parsed=parsed, release_stage=True)

        if pick_status == "need_order_sn":
            await self._send_reply(
                shop_id,
                user_id,
                from_uid,
                _cfg(
                    "address_change_multi_order_text",
                    "亲，您在我店有多个订单，请告知需要修改哪个订单的地址？提供订单号或商品名称即可。",
                ),
                metadata,
            )
            return self._finish(context, metadata, parsed=parsed, stage="address_change")

        if pick_status == "not_found":
            await self._send_reply(
                shop_id,
                user_id,
                from_uid,
                _cfg(
                    "address_change_order_not_found_text",
                    "亲，未找到您提供的订单号，请核对后重新发送~",
                ),
                metadata,
            )
            return self._finish(context, metadata, parsed=parsed, release_stage=True)

        if pick_status == "no_eligible" or brief is None:
            await self._send_reply(
                shop_id,
                user_id,
                from_uid,
                _cfg(
                    "address_change_order_not_eligible_text",
                    "亲，该订单当前状态暂不支持在线改地址，请回复「人工」为您处理~",
                ),
                metadata,
            )
            return self._finish(
                context,
                metadata,
                parsed=parsed,
                order_sn=brief.order_sn if brief else "",
                release_stage=True,
            )

        if brief.eligible == "shipped":
            await self._send_reply(
                shop_id,
                user_id,
                from_uid,
                _cfg(
                    "address_change_shipped_first_text",
                    "亲，您的订单已发货，平台可能不允许修改地址。若您确认仍要修改，请点击【确认改址】按钮（操作后无法撤销），并告知新的收货地址。",
                ),
                metadata,
            )

        extra = {
            "order_sn": brief.order_sn,
            "order_status_str": brief.order_status_str,
            "shipping_status": brief.shipping_status,
            "goods_name": brief.goods_name,
            "address_change_eligible": brief.eligible,
            "parsed_address": {
                "name": parsed.name,
                "mobile": parsed.mobile,
                "province": parsed.province,
                "city": parsed.city,
                "district": parsed.district,
                "detail": parsed.detail,
                "full_text": parsed.full_text,
            },
            "address_before_summary": "",
            "orders_brief": [
                {
                    "order_sn": brief.order_sn,
                    "goods_name": brief.goods_name,
                    "order_status_str": brief.order_status_str,
                }
            ],
        }

        try:
            from core.human_assist_bus import emit_human_assist
            from utils.human_escalation_comfort import send_human_transfer_comfort

            await send_human_transfer_comfort(
                context,
                metadata,
                reason="order_address_change",
            )
            emit_human_assist(
                "order_address_change",
                context,
                metadata,
                text,
                extra=extra,
            )
            _audit_address_change(
                order_sn=brief.order_sn,
                detail=f"改址弹窗已推送 order={brief.order_sn}",
                success=True,
                from_uid=str(from_uid),
                shop_id=str(shop_id),
            )
        except Exception as e:
            self.logger.debug(f"emit_human_assist order_address_change: {e}")
            _audit_address_change(
                order_sn=brief.order_sn,
                detail=f"改址弹窗推送失败: {e}",
                success=False,
                from_uid=str(from_uid),
                shop_id=str(shop_id),
            )

        finish_stage = "await_confirm" if brief.eligible == "shipped" else "address_change"
        finish_release = brief.eligible != "shipped"
        return self._finish(
            context,
            metadata,
            parsed=parsed,
            order_sn=brief.order_sn if brief else "",
            stage=finish_stage,
            release_stage=finish_release,
        )

    async def _send_reply(
        self,
        shop_id: Any,
        user_id: Any,
        from_uid: Any,
        reply: str,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        order_sn: str = "",
    ) -> None:
        ok = await self.send_text_to_buyer(
            shop_id, user_id, from_uid, reply, metadata=metadata
        )
        if not ok:
            self.logger.error("改址话术发送失败")
            _audit_address_change(
                order_sn=order_sn,
                detail="改址话术发送失败",
                success=False,
                from_uid=str(from_uid),
                shop_id=str(shop_id),
            )
