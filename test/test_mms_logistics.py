"""MMS 物流回复与 Handler 集成（开放平台降级为可选）。"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import ChannelType, Context, ContextType
from Channel.pinduoduo.utils.API.chat_orders import (
    format_logistics_order_pick_prompt,
    pick_logistics_order,
)
from Channel.pinduoduo.utils.API.logistics import (
    extract_mms_trace_list,
    format_mms_order_logistics_reply,
    lookup_order_logistics_reply,
    open_platform_logistics_ready,
)
from Message.handlers.order_logistics_handler import OrderLogisticsHandler


def test_format_mms_order_with_trace_list():
    order = {
        "orderSn": "250105-123456789012345",
        "orderStatusStr": "已发货，待签收",
        "shippingStatus": 2,
        "trackingNumber": "YT123456",
        "traceInfoList": [
            {"traceTime": "2026-06-01 10:00", "traceDesc": "已揽收"},
            {"time": "2026-06-02 08:00", "desc": "运输中"},
        ],
    }
    reply = format_mms_order_logistics_reply("250105-123456789012345", order)
    assert "物流轨迹" in reply
    assert "YT123456" in reply
    assert "已揽收" in reply
    assert "运输中" in reply


def test_format_mms_order_status_only():
    order = {
        "orderStatusStr": "未发货，退款成功",
        "shippingStatus": 0,
        "trackingNumber": "",
        "traceInfoList": None,
    }
    reply = format_mms_order_logistics_reply("260528-621239344720457", order)
    assert "未发货，退款成功" in reply
    assert extract_mms_trace_list(order) == []


def test_pick_logistics_single_order_without_sn_in_text():
    orders = [{"orderSn": "260528-621239344720457", "shippingStatus": 0}]
    status, sn, _ = pick_logistics_order(orders, None)
    assert status == "ok"
    assert sn == "260528-621239344720457"


def test_pick_logistics_one_shipped_among_many():
    orders = [
        {"orderSn": "a-1", "shippingStatus": 0, "orderStatusStr": "退款成功"},
        {"orderSn": "b-2", "shippingStatus": 2, "orderStatusStr": "已发货"},
        {"orderSn": "c-3", "shippingStatus": 0, "orderStatusStr": "退款成功"},
    ]
    status, sn, _ = pick_logistics_order(orders, None)
    assert status == "ok"
    assert sn == "b-2"


def test_pick_logistics_multiple_shipped_need_pick():
    orders = [
        {"orderSn": "a-1", "shippingStatus": 2},
        {"orderSn": "b-2", "shippingStatus": 2},
    ]
    status, sn, _ = pick_logistics_order(orders, None)
    assert status == "need_pick"
    assert sn is None
    prompt = format_logistics_order_pick_prompt(orders)
    assert "a-1" in prompt and "b-2" in prompt


def test_lookup_mms_api_error():
    with patch("Channel.pinduoduo.utils.API.logistics.ChatOrdersAPI") as mock_api_cls:
        inst = mock_api_cls.return_value
        inst.fetch_orders_by_buyer_uid.return_value = (False, [])
        reply, sn, need_pick = lookup_order_logistics_reply(
            "s", "u", "buyer1", None
        )
    assert "暂时无法查询" in reply
    assert sn is None
    assert need_pick is False


def test_lookup_auto_resolve_by_uid():
    order = {
        "orderSn": "260528-621239344720457",
        "orderStatusStr": "未发货，退款成功",
        "shippingStatus": 0,
    }
    with patch("Channel.pinduoduo.utils.API.logistics.ChatOrdersAPI") as mock_api_cls:
        inst = mock_api_cls.return_value
        inst.fetch_orders_by_buyer_uid.return_value = (True, [order])
        reply, sn, need_pick = lookup_order_logistics_reply("s", "u", "buyer1", None)
    assert sn == "260528-621239344720457"
    assert need_pick is False
    assert "未发货，退款成功" in reply


def test_lookup_mms_order_not_found():
    with patch("Channel.pinduoduo.utils.API.logistics.ChatOrdersAPI") as mock_api_cls:
        inst = mock_api_cls.return_value
        inst.fetch_orders_by_buyer_uid.return_value = (True, [{"orderSn": "other-1"}])
        reply, sn, need_pick = lookup_order_logistics_reply(
            "s", "u", "buyer1", "250105-123456789012345"
        )
    assert "未在您的订单列表" in reply
    assert sn is None


def test_lookup_open_platform_fallback_when_mms_no_trace():
    order = {
        "orderSn": "250105-123456789012345",
        "orderStatusStr": "已发货",
        "shippingStatus": 2,
        "traceInfoList": None,
    }
    open_raw = {
        "logistics_order_trace_get_response": {
            "trace_list": [{"time": "t1", "action_desc": "派送中"}],
        }
    }
    with patch(
        "Channel.pinduoduo.utils.API.logistics.ChatOrdersAPI"
    ) as mock_api_cls, patch(
        "Channel.pinduoduo.utils.API.logistics.open_platform_logistics_ready",
        return_value=True,
    ), patch(
        "Channel.pinduoduo.utils.API.logistics.LogisticsManager"
    ) as mock_mgr_cls:
        mock_api_cls.return_value.fetch_orders_by_buyer_uid.return_value = (True, [order])
        mock_mgr_cls.return_value.get_order_trace.return_value = open_raw
        reply, sn, need_pick = lookup_order_logistics_reply(
            "s", "u", "buyer1", "250105-123456789012345"
        )
    assert "派送中" in reply
    assert sn == "250105-123456789012345"


def test_lookup_skips_open_when_mms_has_trace():
    order = {
        "orderSn": "250105-123456789012345",
        "traceInfoList": [{"traceDesc": "已签收"}],
    }
    with patch(
        "Channel.pinduoduo.utils.API.logistics.ChatOrdersAPI"
    ) as mock_api_cls, patch(
        "Channel.pinduoduo.utils.API.logistics.open_platform_logistics_ready",
        return_value=True,
    ), patch(
        "Channel.pinduoduo.utils.API.logistics.LogisticsManager"
    ) as mock_mgr_cls:
        mock_api_cls.return_value.fetch_orders_by_buyer_uid.return_value = (True, [order])
        reply, sn, _ = lookup_order_logistics_reply("s", "u", "buyer1", None)
        mock_mgr_cls.return_value.get_order_trace.assert_not_called()
    assert "已签收" in reply
    assert sn == "250105-123456789012345"


@pytest.mark.asyncio
async def test_handler_auto_uid_without_order_sn():
    handler = OrderLogisticsHandler()
    ctx = Context(
        type=ContextType.TEXT,
        content="查物流到哪了",
        channel_type=ChannelType.PINDUODUO,
        kwargs=type(
            "Kwargs",
            (),
            {"from_uid": "b1", "shop_id": "s1", "user_id": "u1"},
        )(),
    )
    meta = {"shop_id": "s1", "user_id": "u1", "from_uid": "b1", "channel_name": "pinduoduo"}
    mock_db = MagicMock()
    mock_db.get_account.return_value = {"id": 1}
    mock_db.get_chat_session_by_buyer.return_value = {"id": 9}
    mock_db.get_session_memory.return_value = {"task_state_json": json.dumps({"stage": "idle"})}

    send_mock = AsyncMock()
    with patch(
        "Channel.pinduoduo.utils.API.logistics.lookup_order_logistics_reply",
        return_value=("订单 x 物流信息", "260528-621239344720457", False),
    ), patch.object(handler, "_send_reply", send_mock), patch(
        "database.db_manager.db_manager", mock_db
    ):
        ok = await handler.handle(ctx, meta)
    assert ok is True
    written = json.loads(mock_db.update_session_memory.call_args.kwargs["task_state_json"])
    assert written["stage"] == "idle"


@pytest.mark.asyncio
async def test_handler_keeps_stage_when_need_pick():
    handler = OrderLogisticsHandler()
    ctx = Context(
        type=ContextType.TEXT,
        content="快递到哪了",
        channel_type=ChannelType.PINDUODUO,
        kwargs=type(
            "Kwargs",
            (),
            {"from_uid": "b1", "shop_id": "s1", "user_id": "u1"},
        )(),
    )
    meta = {"shop_id": "s1", "user_id": "u1", "from_uid": "b1", "channel_name": "pinduoduo"}
    mock_db = MagicMock()
    mock_db.get_account.return_value = {"id": 1}
    mock_db.get_chat_session_by_buyer.return_value = {"id": 9}
    mock_db.get_session_memory.return_value = {"task_state_json": json.dumps({"stage": "idle"})}

    with patch(
        "Channel.pinduoduo.utils.API.logistics.lookup_order_logistics_reply",
        return_value=("请发订单号", None, True),
    ), patch.object(handler, "_send_reply", new_callable=AsyncMock), patch(
        "database.db_manager.db_manager", mock_db
    ):
        await handler.handle(ctx, meta)
    written = json.loads(mock_db.update_session_memory.call_args.kwargs["task_state_json"])
    assert written["stage"] == "logistics"


def test_open_platform_ready_requires_credentials():
    with patch(
        "Channel.pinduoduo.utils.API.logistics.config.get",
        side_effect=lambda key, default=None: {
            "enabled": True,
            "client_id": "",
            "client_secret": "",
            "access_token": "",
        }
        if key == "pinduoduo_open"
        else default,
    ):
        assert open_platform_logistics_ready() is False
    with patch(
        "Channel.pinduoduo.utils.API.logistics.config.get",
        side_effect=lambda key, default=None: {
            "enabled": True,
            "client_id": "a",
            "client_secret": "b",
            "access_token": "c",
        }
        if key == "pinduoduo_open"
        else default,
    ):
        assert open_platform_logistics_ready() is True
