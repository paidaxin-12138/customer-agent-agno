# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""Agent 工具二次校验。"""
from unittest.mock import MagicMock, patch

from utils.agent_tool_guard import (
    allow_transfer_tool_call,
    bind_tool_session_params,
    buyer_message_from_dependencies,
    validate_shop_goods_id,
)


def test_buyer_message_from_dependencies():
    assert buyer_message_from_dependencies({"buyer_message": " 转人工 "}) == "转人工"


def test_transfer_allowed_when_model_escalates_without_explicit_intent():
    ok, msg = allow_transfer_tool_call(
        {
            "shop_id": "s1",
            "user_id": "u1",
            "from_uid": "buyer1",
            "buyer_message": "用了你们的产品过敏了",
        }
    )
    assert ok
    assert msg == ""


def test_transfer_allowed_with_explicit_intent():
    ok, msg = allow_transfer_tool_call(
        {
            "shop_id": "s1",
            "user_id": "u1",
            "from_uid": "buyer1",
            "buyer_message": "我要转人工客服",
        }
    )
    assert ok
    assert msg == ""


def test_transfer_denied_without_session_context():
    ok, msg = allow_transfer_tool_call({"buyer_message": "这个多少钱"})
    assert not ok
    assert "拒绝" in msg


def test_transfer_denied_without_message():
    ok, _ = allow_transfer_tool_call(
        {"shop_id": "s1", "user_id": "u1", "from_uid": "buyer1"}
    )
    assert not ok


def test_bind_session_params_ok():
    deps = {"shop_id": "s1", "user_id": "u1", "from_uid": "buyer1"}
    shop, user, buyer, err = bind_tool_session_params(
        deps, shop_id="s1", user_id="u1", recipient_uid="buyer1"
    )
    assert err == ""
    assert shop == "s1" and user == "u1" and buyer == "buyer1"


def test_bind_session_params_rejects_mismatched_buyer():
    deps = {"shop_id": "s1", "user_id": "u1", "from_uid": "buyer1"}
    _, _, _, err = bind_tool_session_params(
        deps, shop_id="s1", user_id="u1", recipient_uid="other_buyer"
    )
    assert "不一致" in err


@patch("Channel.pinduoduo.utils.API.product_manager.ProductManager")
def test_validate_goods_id_success(mock_pm_cls):
    mock_pm_cls.return_value.get_product_detail.return_value = {
        "success": True,
        "product_info": {"goods_id": 123},
    }
    ok, msg = validate_shop_goods_id("s1", "u1", 123)
    assert ok
    assert msg == ""


@patch("Channel.pinduoduo.utils.API.product_manager.ProductManager")
def test_validate_goods_id_not_found(mock_pm_cls):
    mock_pm_cls.return_value.get_product_detail.return_value = {
        "success": False,
        "error_msg": "商品不存在",
    }
    ok, msg = validate_shop_goods_id("s1", "u1", 999)
    assert not ok
    assert "不存在" in msg
