"""
商家聊天 MMS：买家订单查询（非开放平台）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..base_request import BaseRequest

_ORDER_TIME_KEYS = (
    "payTime",
    "pay_time",
    "orderTime",
    "order_time",
    "confirmTime",
    "confirm_time",
    "createdAt",
    "created_at",
    "orderCreateTime",
    "order_create_time",
    "payTimestamp",
    "pay_timestamp",
    "orderPayTime",
    "order_pay_time",
)


def _chat_mms_headers(cookies: Dict[str, Any]) -> Dict[str, str]:
    anti_content = cookies.get("anti_content") or cookies.get("anti-content", "")
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "anti-content": anti_content,
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://mms.pinduoduo.com",
        "referer": "https://mms.pinduoduo.com/chat-merchant/index.html",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }


# userAllOrder 中 afterSalesStatus 表示已有/进行中售后（与订单卡字段一致）
_ACTIVE_AFTER_SALES_STATUSES = frozenset(
    {2, 3, 4, 5, 7, 8, 14, 15, 16, 18, 21, 22, 27, 31, 32, 33}
)
# payStatus=4 等：平台侧已退款/关闭，不可再代申请
_REFUNDED_PAY_STATUSES = frozenset({4, 6})


def order_after_sales_status(order: Dict[str, Any]) -> Optional[int]:
    if not isinstance(order, dict):
        return None
    after = order.get("afterSalesInfo")
    if isinstance(after, dict) and after.get("afterSalesStatus") is not None:
        try:
            return int(after["afterSalesStatus"])
        except (TypeError, ValueError):
            return None
    return None


def order_merchant_refund_block_reason(order: Dict[str, Any]) -> Optional[str]:
    """
    是否不宜再发 ask_refund_apply 卡。

    Returns:
        None：可尝试发卡
        already_refunded / after_sales_active / preferred_blocked
    """
    if not isinstance(order, dict):
        return "invalid"
    status_str = str(order.get("orderStatusStr") or "")
    if any(
        x in status_str
        for x in ("退款成功", "交易关闭", "已取消", "已关闭", "退款中")
    ):
        return "already_refunded"
    try:
        pay_status = int(order.get("payStatus"))
    except (TypeError, ValueError):
        pay_status = None
    if pay_status in _REFUNDED_PAY_STATUSES:
        return "already_refunded"
    ast = order_after_sales_status(order)
    if ast is not None and ast in _ACTIVE_AFTER_SALES_STATUSES:
        return "after_sales_active"
    return None


def pick_refund_card_order(
    orders: List[Dict[str, Any]],
    preferred_order_sn: Optional[str] = None,
) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[str]]:
    """
  从订单列表挑选可尝试代申请的一单。

    Returns:
        (order_sn, order_rec, block_reason_if_preferred_only)
    """
    if not isinstance(orders, list) or not orders:
        return None, None, None
    pref = (preferred_order_sn or "").strip()
    if pref:
        for order in orders:
            if _order_sn_from_record(order) == pref:
                reason = order_merchant_refund_block_reason(order)
                if reason:
                    return None, order, reason
                return pref, order, None
        return None, None, None
    for order in orders:
        if order_merchant_refund_block_reason(order) is not None:
            continue
        sn = _order_sn_from_record(order)
        if sn:
            return sn, order, None
    return None, None, "no_eligible"


def _order_sn_from_record(order: Dict[str, Any]) -> Optional[str]:
    if not isinstance(order, dict):
        return None
    for key in ("orderSn", "order_sn", "orderSequenceNo", "order_sn_str"):
        val = order.get(key)
        if val:
            return str(val).strip()
    return None


def _refund_amount_fen_from_order(order: Dict[str, Any]) -> Optional[int]:
    """从 MMS userAllOrder 订单记录推断退款金额（分）。"""
    if not isinstance(order, dict):
        return None

    def _positive_int(raw: Any) -> Optional[int]:
        if raw is None:
            return None
        try:
            val = int(float(raw))
        except (TypeError, ValueError):
            return None
        return val if val > 0 else None

    # 聊天订单接口字段已是「分」，勿再 ×100（orderAmount=200 表示 2.00 元）
    for key in (
        "orderAmount",
        "order_amount",
        "goodsAmount",
        "goods_amount",
        "refundAmount",
        "refund_amount",
    ):
        val = _positive_int(order.get(key))
        if val is not None:
            return val

    goods = order.get("orderGoodsList")
    if isinstance(goods, dict):
        val = _positive_int(goods.get("goodsPrice") or goods.get("goods_price"))
        if val is not None:
            return val
    elif isinstance(goods, list):
        for item in goods:
            if not isinstance(item, dict):
                continue
            val = _positive_int(item.get("goodsPrice") or item.get("goods_price"))
            if val is not None:
                return val

    # 其它来源：小于 1e6 按「元」转分
    for key in ("payAmount", "pay_amount"):
        val = _positive_int(order.get(key))
        if val is None:
            continue
        if val >= 1_000_000:
            return val
        return val * 100
    return None


def order_shipping_status(order: Dict[str, Any]) -> int:
    """发货状态：0 未发货，>0 已发货（与 ask_refund_apply user_ship_status 对齐）。"""
    if not isinstance(order, dict):
        return 0
    try:
        return int(order.get("shippingStatus") or 0)
    except (TypeError, ValueError):
        return 0


def resolve_question_type(
    order: Optional[Dict[str, Any]],
    after_sales_type: int,
    *,
    default_shipped: int = 1,
    default_unshipped: int = 0,
) -> int:
    """
    售后原因编码（question_type）。

    未发货快捷退款勿用 1（界面常显示「其他原因」，买家确认会报原因非法且卡片易标已过期）。
    """
    ship = order_shipping_status(order) if order else 0
    if ship == 0 or int(after_sales_type) == 1:
        return default_unshipped
    return default_shipped


def adapt_ask_refund_card_params(
    order: Dict[str, Any],
    after_sales_type: int,
    *,
    exchange_type: int = 4,
    unshipped_refund_type: int = 1,
) -> tuple[int, int]:
    """
    按订单发货状态修正发卡类型与 user_ship_status。

    未发货订单仅支持 after_sales_type=1（未发货退款卡），
    退货退款(3)/换货(4) 会触发 MMS「参数错误」。
    """
    ship = order_shipping_status(order)
    user_ship_status = 1 if ship > 0 else 0
    if ship == 0 and after_sales_type in (3, exchange_type):
        return unshipped_refund_type, user_ship_status
    return after_sales_type, user_ship_status


@dataclass(frozen=True)
class AskRefundApplyParams:
    """ask_refund_apply/send 请求参数（金额单位：分）。"""

    after_sales_type: int
    question_type: int
    refund_amount: int
    user_ship_status: int
    message: str


def refund_card_push_expired(
    state: Optional[Dict[str, Any]] = None,
    mstate: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    type=19 卡片下行是否已不可用。

    有效卡：mstate.status=0 且 expire_text 为空 → 返回 False，可发操作引导。

    失效卡：expire_text 含「过期」（常见 mstate.status=1 且「已过期」），
    表示商家代申请窗口/次数已耗尽，与 valid_time 是否未来无关。
    """
    for block in (state, mstate):
        if not isinstance(block, dict):
            continue
        text = str(block.get("expire_text") or "")
        if "过期" in text:
            return True
    return False


def build_ask_refund_apply_params(
    order_rec: Optional[Dict[str, Any]],
    policy_after_sales_type: int,
    refund_amount_fen: int,
    *,
    default_shipped_question_type: int = 1,
    default_unshipped_question_type: int = 0,
    card_message: Optional[str] = None,
) -> AskRefundApplyParams:
    """
    按订单发货状态生成正确的 MMS 发卡参数。

    - 金额：userAllOrder 字段已是分，勿 ×100
    - 未发货：after_sales_type→1，question_type→0（勿用 1「其他原因」）
  """
    order = order_rec if isinstance(order_rec, dict) else {}
    after_sales_type, user_ship_status = adapt_ask_refund_card_params(
        order, int(policy_after_sales_type)
    )
    question_type = resolve_question_type(
        order,
        after_sales_type,
        default_shipped=default_shipped_question_type,
        default_unshipped=default_unshipped_question_type,
    )
    amount = int(refund_amount_fen)
    if amount <= 0:
        resolved = _refund_amount_fen_from_order(order)
        if resolved:
            amount = resolved
    return AskRefundApplyParams(
        after_sales_type=after_sales_type,
        question_type=question_type,
        refund_amount=amount,
        user_ship_status=user_ship_status,
        message="" if card_message is None else str(card_message),
    )


def _parse_unix_timestamp(raw: Any) -> Optional[float]:
    """将 MMS 订单时间字段转为 Unix 秒（支持秒/毫秒）。"""
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if val <= 0:
        return None
    if val > 1e12:
        val = val / 1000.0
    return val


def order_purchase_unix_ts(order: Dict[str, Any]) -> Optional[float]:
    """从订单记录提取购买/支付时间（Unix 秒）。"""
    if not isinstance(order, dict):
        return None
    candidates: List[float] = []
    for key in _ORDER_TIME_KEYS:
        ts = _parse_unix_timestamp(order.get(key))
        if ts is not None:
            candidates.append(ts)
    nested = order.get("orderInfo") or order.get("order_info")
    if isinstance(nested, dict):
        for key in _ORDER_TIME_KEYS:
            ts = _parse_unix_timestamp(nested.get(key))
            if ts is not None:
                candidates.append(ts)
    if not candidates:
        return None
    return min(candidates)


def days_since_purchase(
    order: Dict[str, Any], *, now: Optional[float] = None
) -> Optional[float]:
    """自购买/支付起的天数；无法解析时返回 None。"""
    ts = order_purchase_unix_ts(order)
    if ts is None:
        return None
    ref = now if now is not None else time.time()
    return max(0.0, (ref - ts) / 86400.0)


def find_order_by_sn(
    orders: List[Dict[str, Any]], order_sn: str
) -> Optional[Dict[str, Any]]:
    target = (order_sn or "").strip()
    if not target:
        return None
    for order in orders:
        if _order_sn_from_record(order) == target:
            return order
    return None


def _order_sns_from_list(orders: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for order in orders:
        sn = _order_sn_from_record(order)
        if sn:
            out.append(sn)
    return out


class ChatOrdersAPI(BaseRequest):
    """聊天场景订单相关 MMS 接口。"""

    def get_user_orders(self, buyer_uid: str, page_size: int = 10) -> List[Dict[str, Any]]:
        """兼容旧调用：仅返回订单列表（接口失败时为空列表）。"""
        _api_ok, orders = self.fetch_orders_by_buyer_uid(buyer_uid, page_size=page_size)
        return orders

    def fetch_orders_by_buyer_uid(
        self, buyer_uid: str, page_size: int = 10
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        按买家 UID 拉取订单。

        Returns:
            (api_ok, orders)：api_ok=False 表示 MMS 请求失败；True 且 orders 为空表示该 UID 下未查到订单。
        """
        url = "https://mms.pinduoduo.com/latitude/order/userAllOrder"
        data = {"uid": str(buyer_uid), "pageSize": int(page_size)}
        result = self.post(url, json_data=data, headers=_chat_mms_headers(self.cookies))
        if not result or not result.get("success"):
            self.logger.warning(f"userAllOrder 失败 uid={buyer_uid}: {result}")
            return False, []
        orders = result.get("result", {}).get("orders") or []
        if not isinstance(orders, list):
            return True, []
        return True, orders

    def buyer_has_orders(self, buyer_uid: str, page_size: int = 10) -> Optional[bool]:
        """
        按买家 UID 判断是否有关联订单。

        Returns:
            True/False：接口成功且（无）订单；
            None：接口调用失败，无法判断。
        """
        api_ok, orders = self.fetch_orders_by_buyer_uid(buyer_uid, page_size=page_size)
        if not api_ok:
            return None
        return len(_order_sns_from_list(orders)) > 0

    def resolve_order_for_buyer(
        self, buyer_uid: str, preferred_order_sn: Optional[str] = None, page_size: int = 10
    ) -> Tuple[str, Optional[str], List[Dict[str, Any]]]:
        """
        按买家 UID 解析用于发卡的订单号。

        Returns:
            (status, order_sn, orders)
            status:
              - ok：找到 order_sn
              - no_orders：接口成功但该 UID 下无有效订单
              - no_eligible：有订单但均不可代申请（已退款/售后中等）
              - api_error：MMS 查询失败
        """
        api_ok, orders = self.fetch_orders_by_buyer_uid(buyer_uid, page_size=page_size)
        if not api_ok:
            return "api_error", None, []
        sns = _order_sns_from_list(orders)
        if not sns:
            return "no_orders", None, orders
        pref = (preferred_order_sn or "").strip()
        if pref and pref not in sns:
            self.logger.info(
                f"买家 {buyer_uid} 订单列表中未找到 {pref}，改用可代申请订单"
            )
            pref = ""
        sn, rec, block = pick_refund_card_order(orders, pref or None)
        if sn:
            return "ok", sn, orders
        blocked_sn = _order_sn_from_record(rec) if rec else None
        if block in ("already_refunded", "after_sales_active", "preferred_blocked"):
            return "no_eligible", blocked_sn, orders
        return "no_eligible", None, orders

    def get_order_pickup_info(self, order_sn: str) -> Dict[str, Any]:
        """售后申请卡片所需 reposeInfo（收件信息等）。"""
        url = "https://mms.pinduoduo.com/latitude/afterSales/replenishment/getDetail"
        data = {"orderSn": str(order_sn)}
        result = self.post(url, json_data=data, headers=_chat_mms_headers(self.cookies))
        if not result or not result.get("success"):
            self.logger.debug(f"getDetail 失败 order_sn={order_sn}: {result}")
            return {}
        payload = result.get("result")
        return payload if isinstance(payload, dict) else {}

    def pick_latest_order_sn(self, buyer_uid: str) -> Optional[str]:
        _status, sn, _orders = self.resolve_order_for_buyer(buyer_uid)
        return sn if _status == "ok" else None

    def pick_refund_amount_fen(
        self,
        buyer_uid: str,
        order_sn: str,
        orders: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[int]:
        if orders is None:
            _api_ok, orders = self.fetch_orders_by_buyer_uid(buyer_uid)
            if not _api_ok:
                return None
        for order in orders:
            if _order_sn_from_record(order) == order_sn:
                return _refund_amount_fen_from_order(order)
        return None


__all__ = [
    "ChatOrdersAPI",
    "_order_sn_from_record",
    "_order_sns_from_list",
    "_refund_amount_fen_from_order",
    "AskRefundApplyParams",
    "adapt_ask_refund_card_params",
    "build_ask_refund_apply_params",
    "refund_card_push_expired",
    "resolve_question_type",
    "order_purchase_unix_ts",
    "order_shipping_status",
    "order_after_sales_status",
    "order_merchant_refund_block_reason",
    "pick_refund_card_order",
    "days_since_purchase",
    "find_order_by_sn",
]
