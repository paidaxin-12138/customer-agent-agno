"""改址：订单选择、可改性判断。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from Channel.pinduoduo.utils.API.chat_orders import (
    _order_sn_from_record,
    order_after_sales_status,
    order_merchant_refund_block_reason,
    order_shipping_status,
)
from utils.address_parse import ParsedAddress

_ACTIVE_AFTER_SALES = frozenset({2, 3, 4, 5, 7, 8, 14, 15, 16, 18, 21, 22, 27, 31, 32, 33})


@dataclass
class OrderBrief:
    order_sn: str
    order_status_str: str
    shipping_status: int
    goods_name: str
    eligible: str
    pay_time: int = 0


def _goods_name(order: Dict[str, Any]) -> str:
    g = order.get("orderGoodsList")
    if isinstance(g, dict):
        return str(g.get("goodsName") or g.get("goods_name") or "")
    if isinstance(g, list) and g:
        return str(g[0].get("goodsName") or g[0].get("goods_name") or "")
    return ""


def _pay_time(order: Dict[str, Any]) -> int:
    for k in ("payTime", "pay_time", "orderTime", "order_time", "confirmTime"):
        v = order.get(k)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
    return 0


def address_change_eligible(order: Dict[str, Any]) -> str:
    block = order_merchant_refund_block_reason(order)
    if block in ("already_refunded",):
        return "blocked_refund"
    ast = order_after_sales_status(order)
    if ast is not None and ast in _ACTIVE_AFTER_SALES:
        return "blocked_after_sales"
    ship = order_shipping_status(order)
    if ship > 0:
        return "shipped"
    return "ok"


def order_brief(order: Dict[str, Any]) -> OrderBrief:
    sn = _order_sn_from_record(order) or ""
    return OrderBrief(
        order_sn=sn,
        order_status_str=str(order.get("orderStatusStr") or ""),
        shipping_status=order_shipping_status(order),
        goods_name=_goods_name(order),
        pay_time=_pay_time(order),
        eligible=address_change_eligible(order),
    )


def pick_order_for_address_change(
    orders: List[Dict[str, Any]],
    text: str,
    parsed: ParsedAddress,
) -> Tuple[Optional[OrderBrief], str]:
    """
    Returns:
        (order_brief, status)
        status: ok | no_orders | need_order_sn | not_found | no_eligible
    """
    if not orders:
        return None, "no_orders"

    briefs = [order_brief(o) for o in orders if _order_sn_from_record(o)]
    if not briefs:
        return None, "no_orders"

    text_l = (text or "").lower()
    order_sn_pat = re.search(r"\d{6}-\d{15,24}", text or "")
    if order_sn_pat:
        sn = order_sn_pat.group(0)
        for b in briefs:
            if b.order_sn == sn:
                if b.eligible in ("blocked_refund", "blocked_after_sales"):
                    return b, "no_eligible"
                return b, "ok"
        return None, "not_found"

    for b in briefs:
        if b.goods_name and b.goods_name in (text or ""):
            if b.eligible in ("blocked_refund", "blocked_after_sales"):
                return b, "no_eligible"
            return b, "ok"

    if len(briefs) >= 2:
        return None, "need_order_sn"

    b = briefs[0]
    if b.eligible in ("blocked_refund", "blocked_after_sales"):
        return b, "no_eligible"
    return b, "ok"


def mask_address_summary(text: str) -> str:
    s = (text or "").strip()
    if len(s) <= 12:
        return s
    return s[:6] + "…" + s[-4:]
