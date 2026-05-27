"""买家 UID 订单解析单元测试。"""

from Channel.pinduoduo.utils.API.chat_orders import (
    ChatOrdersAPI,
    _order_sns_from_list,
)


def test_order_sns_from_list():
    orders = [{"orderSn": "250101-111"}, {"foo": 1}, {"order_sn": "250102-222"}]
    assert _order_sns_from_list(orders) == ["250101-111", "250102-222"]


def test_resolve_order_for_buyer_no_orders(monkeypatch):
    api = ChatOrdersAPI.__new__(ChatOrdersAPI)

    def fake_fetch(_uid, page_size=10):
        return True, []

    monkeypatch.setattr(api, "fetch_orders_by_buyer_uid", fake_fetch)
    status, sn, orders = api.resolve_order_for_buyer("buyer123")
    assert status == "no_orders"
    assert sn is None
    assert orders == []


def test_resolve_order_for_buyer_preferred(monkeypatch):
    api = ChatOrdersAPI.__new__(ChatOrdersAPI)
    sample = [{"orderSn": "250101-111"}, {"orderSn": "250102-222"}]

    def fake_fetch(_uid, page_size=10):
        return True, sample

    monkeypatch.setattr(api, "fetch_orders_by_buyer_uid", fake_fetch)
    status, sn, _ = api.resolve_order_for_buyer("buyer123", "250102-222")
    assert status == "ok"
    assert sn == "250102-222"
