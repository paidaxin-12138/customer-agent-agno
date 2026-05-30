"""申请退换货处理器单元测试（无真实 MMS 调用）。"""

from Message.handlers.after_sales_apply_handler import _order_sn_from_order_info
from utils.after_sales_policy import is_after_sales_related
from Message.handlers.order_logistics_handler import _extract_order_sn


def test_refund_intent():
    assert is_after_sales_related("我想退货")
    assert is_after_sales_related("怎么退款啊")
    assert is_after_sales_related("想换货")
    assert not is_after_sales_related("物流到哪了")


def test_extract_order_sn():
    sn = _extract_order_sn("订单号：250105-123456789012345")
    assert sn == "250105-123456789012345"


def test_order_info_sn():
    assert _order_sn_from_order_info({"order_id": "250105-999"}) == "250105-999"
