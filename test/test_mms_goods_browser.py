"""MMS 商品浏览器风控识别与解析辅助测试。"""
from Channel.pinduoduo.utils.mms_goods_browser import (
    is_risk_blocked_response,
    normalize_risk_error_message,
)
from Channel.pinduoduo.utils.API.product_manager import ProductManager


def test_is_risk_blocked_54001():
    raw = {
        "error_code": 54001,
        "error_msg": "操作太过频繁，请稍后再试！",
        "result": {"verifyAuthToken": "abc"},
    }
    assert is_risk_blocked_response(raw) is True
    msg = normalize_risk_error_message(raw)
    assert "风控" in msg
    assert "频繁" not in msg or "误导" in msg


def test_parse_list_field_from_browser_shape():
    pm = ProductManager()
    raw = {
        "success": True,
        "result": {"total": 1, "list": [{"goods_id": 1, "goods_name": "A", "quantity": 1}]},
    }
    out = pm._parse_mall_goods_list(raw)
    assert out["total"] == 1
    assert out["products"][0]["goods_id"] == 1
