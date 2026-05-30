"""退换货天数策略单元测试。"""

import time

from utils.after_sales_policy import (
    AFTER_SALES_EXCHANGE,
    AFTER_SALES_RETURN_REFUND,
    AFTER_SALES_UNSHIPPED_REFUND,
    AfterSalesAction,
    AfterSalesIntent,
    decide_after_sales,
    detect_after_sales_intent,
    is_after_sales_related,
)
from Channel.pinduoduo.utils.API.chat_orders import (
    days_since_purchase,
    order_purchase_unix_ts,
)


def test_detect_intent():
    assert detect_after_sales_intent("我想换货") == AfterSalesIntent.EXCHANGE
    assert detect_after_sales_intent("我要退货退款") == AfterSalesIntent.RETURN_REFUND
    assert detect_after_sales_intent("仅退款") == AfterSalesIntent.REFUND_ONLY
    assert detect_after_sales_intent("怎么退款") == AfterSalesIntent.RETURN_REFUND
    assert detect_after_sales_intent("退换货") == AfterSalesIntent.RETURN_REFUND


def test_unshipped_refund():
    d = decide_after_sales(0.5, AfterSalesIntent.GENERAL, user_ship_status=0)
    assert d.action == AfterSalesAction.SEND_CARD
    assert d.after_sales_type == AFTER_SALES_UNSHIPPED_REFUND
    assert d.reason == "unshipped_refund"

    d2 = decide_after_sales(0.5, AfterSalesIntent.RETURN_REFUND, user_ship_status=0)
    assert d2.after_sales_type == AFTER_SALES_UNSHIPPED_REFUND

    d3 = decide_after_sales(0.5, AfterSalesIntent.EXCHANGE, user_ship_status=0)
    assert d3.action == AfterSalesAction.TRANSFER_HUMAN
    assert d3.reason == "unshipped_exchange"


def test_within_7_days():
    d = decide_after_sales(3.0, AfterSalesIntent.GENERAL)
    assert d.action == AfterSalesAction.SEND_CARD
    assert d.after_sales_type == AFTER_SALES_RETURN_REFUND

    d2 = decide_after_sales(3.0, AfterSalesIntent.EXCHANGE)
    assert d2.after_sales_type == AFTER_SALES_EXCHANGE

    d3 = decide_after_sales(3.0, AfterSalesIntent.REFUND_ONLY)
    assert d3.action == AfterSalesAction.TRANSFER_HUMAN


def test_mid_window():
    d = decide_after_sales(30.0, AfterSalesIntent.GENERAL)
    assert d.action == AfterSalesAction.SEND_CARD
    assert d.after_sales_type == AFTER_SALES_EXCHANGE

    d2 = decide_after_sales(30.0, AfterSalesIntent.RETURN_REFUND)
    assert d2.action == AfterSalesAction.TRANSFER_HUMAN

    d3 = decide_after_sales(30.0, AfterSalesIntent.EXCHANGE)
    assert d3.after_sales_type == AFTER_SALES_EXCHANGE


def test_over_90():
    d = decide_after_sales(100.0, AfterSalesIntent.GENERAL)
    assert d.action == AfterSalesAction.TRANSFER_HUMAN


def test_boundary_7_days():
    assert (
        decide_after_sales(7.0, AfterSalesIntent.GENERAL).after_sales_type
        == AFTER_SALES_RETURN_REFUND
    )
    assert (
        decide_after_sales(7.01, AfterSalesIntent.GENERAL).after_sales_type
        == AFTER_SALES_EXCHANGE
    )


def test_order_purchase_ts():
    now = time.time()
    order = {"payTime": int(now - 5 * 86400)}
    assert order_purchase_unix_ts(order) is not None
    days = days_since_purchase(order, now=now)
    assert days is not None
    assert 4.9 < days < 5.1


def test_is_after_sales_related():
    assert is_after_sales_related("想换货")
    assert is_after_sales_related("退货")
    assert not is_after_sales_related("物流到哪了")
