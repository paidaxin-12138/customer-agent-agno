"""
退换货发卡策略：按发货状态、购买天数与买家明确意图决定发卡或转人工。

规则（默认，天数基于订单支付/下单时间，见 chat_orders.days_since_purchase）：
- **未发货**：发未发货退款卡(1)；买家明确换货 → 转人工
- **已发货且 ≤7 天（含第 7 天）**：默认退货退款卡(3)；买家明确换货 → 换货卡(4)
- **已发货且 7＜天数≤90**：发换货卡(4)；买家明确退货退款/仅退款 → 转人工
- **＞90 天**：转人工
- AI 不发送仅退款卡(2)；已发货「仅退款」转人工
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# MMS after_sales_type（与 send_message.send_ask_refund_apply 一致）
AFTER_SALES_UNSHIPPED_REFUND = 1
AFTER_SALES_RETURN_REFUND = 3
AFTER_SALES_EXCHANGE = 4
AFTER_SALES_REFUND_ONLY = 2  # 禁止 AI 发送


class AfterSalesIntent(str, Enum):
    GENERAL = "general"
    EXCHANGE = "exchange"
    RETURN_REFUND = "return_refund"
    REFUND_ONLY = "refund_only"


class AfterSalesAction(str, Enum):
    SEND_CARD = "send_card"
    TRANSFER_HUMAN = "transfer_human"


@dataclass(frozen=True)
class AfterSalesDecision:
    action: AfterSalesAction
    after_sales_type: Optional[int] = None
    reason: str = ""


_REFUND_ONLY_PHRASES = (
    "仅退款",
    "只退款",
    "不退货只退",
    "不退货 只退",
    "不用退货",
    "不想退货",
    "只要退款不退货",
    "只退钱不退货",
)

_RETURN_REFUND_PHRASES = (
    "退货退款",
    "退换货",
    "退换",
    "申请退货",
    "申请退款",
    "退货",
    "退款",
    "退钱",
    "怎么退",
    "如何退",
    "想退",
    "要退",
    "不想要了",
    "拒收",
    "申请售后",
    "售后申请",
    "能退吗",
    "可以退吗",
    "能不能退",
)

_EXCHANGE_PHRASES = (
    "换货",
    "换一个",
    "想换",
    "更换",
    "能换吗",
    "可以换吗",
    "怎么换",
    "如何换",
    "换一款",
    "换个",
)


def is_after_sales_related(text: str) -> bool:
    """是否属于售后/退换货类咨询（用于处理器 can_handle）。"""
    return detect_after_sales_intent(text) != AfterSalesIntent.GENERAL or _has_loose_after_sales(
        text
    )


def _has_loose_after_sales(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return any(p in t for p in _RETURN_REFUND_PHRASES) or any(p in t for p in _EXCHANGE_PHRASES)


def detect_after_sales_intent(text: str) -> AfterSalesIntent:
    """
    识别买家明确意图；未强调换货/仅退款时视为 GENERAL（走默认卡类型）。
    """
    t = (text or "").strip()
    if not t:
        return AfterSalesIntent.GENERAL

    if any(p in t for p in _REFUND_ONLY_PHRASES):
        return AfterSalesIntent.REFUND_ONLY

    # 「退换货」等优先于单独「换货」
    if any(p in t for p in ("退货退款", "退换货", "退换", "申请退货", "退货", "退款", "退钱")):
        return AfterSalesIntent.RETURN_REFUND

    if any(p in t for p in _EXCHANGE_PHRASES):
        return AfterSalesIntent.EXCHANGE

    if any(p in t for p in _RETURN_REFUND_PHRASES):
        return AfterSalesIntent.RETURN_REFUND

    return AfterSalesIntent.GENERAL


def decide_after_sales(
    days_since_purchase: Optional[float],
    intent: AfterSalesIntent,
    *,
    user_ship_status: Optional[int] = None,
    return_refund_days: float = 7.0,
    exchange_max_days: float = 90.0,
) -> AfterSalesDecision:
    """
    根据发货状态、购买天数与意图返回发卡或转人工决策。

    user_ship_status: 0 未发货，>0 已发货；None 时按已发货规则处理。
    days_since_purchase: 通常按 payTime 距今天数（作收货后时效近似）。
    """
    if user_ship_status == 0:
        if intent == AfterSalesIntent.EXCHANGE:
            return AfterSalesDecision(
                AfterSalesAction.TRANSFER_HUMAN,
                reason="unshipped_exchange",
            )
        return AfterSalesDecision(
            AfterSalesAction.SEND_CARD,
            after_sales_type=AFTER_SALES_UNSHIPPED_REFUND,
            reason="unshipped_refund",
        )

    if intent == AfterSalesIntent.REFUND_ONLY:
        return AfterSalesDecision(
            AfterSalesAction.TRANSFER_HUMAN,
            reason="refund_only",
        )

    if days_since_purchase is None:
        return AfterSalesDecision(
            AfterSalesAction.TRANSFER_HUMAN,
            reason="unknown_purchase_time",
        )

    if days_since_purchase > exchange_max_days:
        return AfterSalesDecision(
            AfterSalesAction.TRANSFER_HUMAN,
            reason="over_max_days",
        )

    if days_since_purchase <= return_refund_days:
        if intent == AfterSalesIntent.EXCHANGE:
            return AfterSalesDecision(
                AfterSalesAction.SEND_CARD,
                after_sales_type=AFTER_SALES_EXCHANGE,
                reason="within_7d_exchange",
            )
        return AfterSalesDecision(
            AfterSalesAction.SEND_CARD,
            after_sales_type=AFTER_SALES_RETURN_REFUND,
            reason="within_7d_return_refund",
        )

    # return_refund_days < days <= exchange_max_days
    if intent in (AfterSalesIntent.RETURN_REFUND, AfterSalesIntent.REFUND_ONLY):
        return AfterSalesDecision(
            AfterSalesAction.TRANSFER_HUMAN,
            reason="mid_window_return_refund",
        )
    return AfterSalesDecision(
        AfterSalesAction.SEND_CARD,
        after_sales_type=AFTER_SALES_EXCHANGE,
        reason="mid_window_exchange",
    )
