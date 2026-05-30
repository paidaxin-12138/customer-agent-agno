"""MMS 订单金额与发卡参数修正。"""

from Channel.pinduoduo.utils.API.chat_orders import (
    _refund_amount_fen_from_order,
    adapt_ask_refund_card_params,
    build_ask_refund_apply_params,
    order_merchant_refund_block_reason,
    order_shipping_status,
    pick_refund_card_order,
    resolve_question_type,
)


def test_refund_amount_user_all_order_is_fen():
    order = {"orderAmount": 200, "goodsAmount": 200}
    assert _refund_amount_fen_from_order(order) == 200


def test_refund_amount_from_goods_list():
    order = {"orderGoodsList": {"goodsPrice": 1990}}
    assert _refund_amount_fen_from_order(order) == 1990


def test_adapt_unshipped_return_refund_to_type_1():
    order = {"shippingStatus": 0}
    card_type, ship = adapt_ask_refund_card_params(order, 3)
    assert card_type == 1
    assert ship == 0


def test_adapt_shipped_keeps_type_3():
    order = {"shippingStatus": 2}
    card_type, ship = adapt_ask_refund_card_params(order, 3)
    assert card_type == 3
    assert ship == 1


def test_order_shipping_status():
    assert order_shipping_status({"shippingStatus": 0}) == 0
    assert order_shipping_status({"shippingStatus": 2}) == 2


def test_resolve_question_type_unshipped():
    assert resolve_question_type({"shippingStatus": 0}, 1) == 0
    assert resolve_question_type({"shippingStatus": 0}, 3, default_unshipped=0) == 0


def test_resolve_question_type_shipped():
    assert resolve_question_type({"shippingStatus": 2}, 3, default_shipped=1) == 1


def test_build_ask_refund_apply_params_unshipped():
    order = {"shippingStatus": 0, "orderAmount": 200}
    p = build_ask_refund_apply_params(order, 3, 0)
    assert p.after_sales_type == 1
    assert p.question_type == 0
    assert p.refund_amount == 200
    assert p.user_ship_status == 0


def test_order_merchant_refund_block_refunded():
    order = {
        "orderStatusStr": "未发货，退款成功",
        "payStatus": 4,
        "afterSalesInfo": {"afterSalesStatus": 5},
    }
    assert order_merchant_refund_block_reason(order) == "already_refunded"


def test_pick_refund_card_order_skips_refunded():
    orders = [
        {"orderSn": "a", "payStatus": 4, "orderStatusStr": "退款成功"},
        {"orderSn": "b", "payStatus": 2, "shippingStatus": 0, "orderAmount": 100},
    ]
    sn, rec, block = pick_refund_card_order(orders)
    assert sn == "b"
    assert block is None
    sn2, _, block2 = pick_refund_card_order(orders, "a")
    assert sn2 is None
    assert block2 == "already_refunded"
