"""改址订单选择策略。"""

from utils.address_change_policy import pick_order_for_address_change, order_brief
from utils.address_parse import parse_address_from_text


def _order(sn: str, ship: int = 0, goods: str = "美甲灯", status: str = "未发货"):
    return {
        "orderSn": sn,
        "shippingStatus": ship,
        "orderStatusStr": status,
        "orderGoodsList": {"goodsName": goods},
        "payStatus": 2,
    }


def test_pick_single_order():
    orders = [_order("260528-123456789012345")]
    parsed = parse_address_from_text(
        "改地址 广东省深圳市南山区xx路1号 李四 13900139000"
    )
    brief, status = pick_order_for_address_change(orders, "改地址 ...", parsed)
    assert status == "ok"
    assert brief is not None
    assert brief.order_sn == "260528-123456789012345"


def test_pick_need_order_sn_when_multiple():
    orders = [
        _order("260528-111111111111111", goods="商品A"),
        _order("260528-222222222222222", goods="商品B"),
    ]
    parsed = parse_address_from_text(
        "改地址 广东省深圳市南山区xx路1号 李四 13900139000"
    )
    brief, status = pick_order_for_address_change(orders, "改地址 ...", parsed)
    assert status == "need_order_sn"
    assert brief is None


def test_pick_by_order_sn_in_text():
    orders = [
        _order("260528-111111111111111"),
        _order("260528-222222222222222"),
    ]
    parsed = parse_address_from_text(
        "改地址 260528-222222222222222 广东省深圳市南山区xx路1号 李四 13900139000"
    )
    brief, status = pick_order_for_address_change(
        orders,
        "改地址 260528-222222222222222 ...",
        parsed,
    )
    assert status == "ok"
    assert brief.order_sn == "260528-222222222222222"


def test_shipped_eligible():
    b = order_brief(_order("260528-1", ship=2))
    assert b.eligible == "shipped"
