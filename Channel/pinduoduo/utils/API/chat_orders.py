"""
商家聊天 MMS：买家订单查询（非开放平台）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..base_request import BaseRequest


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


def _order_sn_from_record(order: Dict[str, Any]) -> Optional[str]:
    if not isinstance(order, dict):
        return None
    for key in ("orderSn", "order_sn", "orderSequenceNo", "order_sn_str"):
        val = order.get(key)
        if val:
            return str(val).strip()
    return None


def _refund_amount_fen_from_order(order: Dict[str, Any]) -> Optional[int]:
    """从订单记录推断退款金额（分）。"""
    if not isinstance(order, dict):
        return None
    for key in (
        "refundAmount",
        "refund_amount",
        "payAmount",
        "pay_amount",
        "orderAmount",
        "order_amount",
        "goodsAmount",
        "goods_amount",
    ):
        raw = order.get(key)
        if raw is None:
            continue
        try:
            val = int(float(raw))
        except (TypeError, ValueError):
            continue
        if val <= 0:
            continue
        # 大于 1e6 视为已是分，否则按元转分
        if val < 1_000_000:
            return val * 100
        return val
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
              - api_error：MMS 查询失败
        """
        api_ok, orders = self.fetch_orders_by_buyer_uid(buyer_uid, page_size=page_size)
        if not api_ok:
            return "api_error", None, []
        sns = _order_sns_from_list(orders)
        if not sns:
            return "no_orders", None, orders
        pref = (preferred_order_sn or "").strip()
        if pref and pref in sns:
            return "ok", pref, orders
        if pref and pref not in sns:
            self.logger.info(
                f"买家 {buyer_uid} 订单列表中未找到 {pref}，使用最近一单 {sns[0]}"
            )
        return "ok", sns[0], orders

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
]
