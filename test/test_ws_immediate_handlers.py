"""WebSocket 立即处理 handler 单测。"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import ChannelType, Context, ContextType
from Channel.pinduoduo.ws_immediate_handlers import (
    handle_immediate_message,
    handle_inbound_transfer,
    handle_mall_cs_message,
    handle_mall_system_msg,
)


def _kwargs(**overrides):
    base = {
        "from_user": "system",
        "from_uid": "buyer-1",
        "shop_id": "570414651",
        "user_id": "184046586",
    }
    base.update(overrides)
    return type("K", (), base)()


@pytest.mark.asyncio
async def test_auth_ok_notifies_success():
    from Channel.pinduoduo.ws_auth_notify import (
        clear_auth_success_callback,
        register_auth_success_callback,
    )

    cb = MagicMock()
    register_auth_success_callback("570414651_184046586", cb)
    ctx = Context(
        type=ContextType.AUTH,
        content=json.dumps({"result": "ok"}),
        channel_type=ChannelType.PINDUODUO,
        kwargs=_kwargs(),
    )
    try:
        await handle_immediate_message(
            ctx,
            channel_name="pinduoduo",
            shop_id="570414651",
            user_id="184046586",
            username="shop1",
            queue_name="pdd_570414651",
            ws_connections={},
        )
    finally:
        clear_auth_success_callback("570414651_184046586")
    cb.assert_called_once()


@pytest.mark.asyncio
async def test_auth_fail_closes_websocket():
    ctx = Context(
        type=ContextType.AUTH,
        content=json.dumps({"result": "fail"}),
        channel_type=ChannelType.PINDUODUO,
        kwargs=_kwargs(),
    )
    ws = MagicMock()
    ws_connections = {"570414651_184046586": ws}
    close_mock = AsyncMock()

    with patch(
        "Channel.pinduoduo.ws_connection.safe_close_websocket",
        close_mock,
    ):
        await handle_immediate_message(
            ctx,
            channel_name="pinduoduo",
            shop_id="570414651",
            user_id="184046586",
            username="shop1",
            queue_name="pdd_570414651",
            ws_connections=ws_connections,
        )

    close_mock.assert_awaited_once()
    assert close_mock.call_args[0][0] is ws


@pytest.mark.asyncio
async def test_withdraw_sends_rose():
    ctx = Context(
        type=ContextType.WITHDRAW,
        content="撤回",
        channel_type=ChannelType.PINDUODUO,
        kwargs=_kwargs(from_uid="buyer-99"),
    )
    send = MagicMock()

    with patch(
        "Channel.pinduoduo.utils.API.send_message.SendMessage",
        return_value=send,
    ):
        await handle_immediate_message(
            ctx,
            channel_name="pinduoduo",
            shop_id="570414651",
            user_id="184046586",
            username="shop1",
            queue_name="pdd_570414651",
            ws_connections={},
        )

    send.send_text.assert_called_once_with("buyer-99", "[玫瑰]")


@pytest.mark.asyncio
async def test_inbound_transfer_takeover_and_notice(monkeypatch):
    ctx = Context(
        type=ContextType.TRANSFER,
        content=json.dumps({"from_uid": "x", "to_uid": "4216881609"}),
        channel_type=ChannelType.PINDUODUO,
        kwargs=_kwargs(),
    )
    send = MagicMock()
    takeover = AsyncMock(return_value=True)

    monkeypatch.setattr(
        "utils.transfer_takeover.config.get",
        lambda key, default=None: {
            "chat.inbound_transfer_buyer_notice": "已为您接入",
            "chat.transfer_auto_rose_enabled": False,
        }.get(key, default),
    )

    with (
        patch(
            "utils.pdd_transfer.resolve_buyer_uid_from_transfer",
            return_value="4216881609",
        ),
        patch(
            "utils.transfer_takeover.apply_inbound_transfer_takeover",
            takeover,
        ),
    ):
        await handle_inbound_transfer(
            ctx,
            channel_name="pinduoduo",
            shop_id="570414651",
            user_id="184046586",
            username="shop1",
            queue_name="pdd_570414651",
            send_message=send,
        )

    takeover.assert_awaited_once()
    send.send_text.assert_called_once_with("4216881609", "已为您接入")


@pytest.mark.asyncio
async def test_mall_cs_expired_card_sends_notice(monkeypatch):
    inner = {
        "event": "ask_refund_card_push",
        "to_uid": "4216881609",
        "order_sn": "260527-006427778640457",
        "mstate_status": 1,
        "mstate_expire_text": "已过期",
        "state_expire_text": "已过期",
    }
    ctx = Context(
        type=ContextType.MALL_CS,
        content=json.dumps(inner, ensure_ascii=False),
        channel_type=ChannelType.PINDUODUO,
        kwargs=_kwargs(),
    )
    send = MagicMock()
    monkeypatch.setattr(
        "utils.merchant_refund_apply_record.gate_notice",
        lambda gate: "卡片已过期",
    )

    with (
        patch(
            "utils.merchant_refund_apply_record.update_apply_from_card_push"
        ),
        patch(
            "utils.merchant_refund_apply_record.get_apply_counts",
            return_value={"order_total": 1},
        ),
        patch("utils.session_order_cache.mark_refund_card_unusable"),
    ):
        await handle_mall_cs_message(
            ctx, "570414651", "184046586", send
        )

    send.send_text.assert_called_once_with("4216881609", "卡片已过期")


@pytest.mark.asyncio
async def test_mall_system_refund_expired_skips_duplicate_notice():
    inner = {
        "event": "refund_card_expired",
        "user_id": "4216881609",
        "msg_id": "1779867492174",
    }
    ctx = Context(
        type=ContextType.MALL_SYSTEM_MSG,
        content=json.dumps(inner, ensure_ascii=False),
        channel_type=ChannelType.PINDUODUO,
        kwargs=_kwargs(),
    )
    send = MagicMock()
    mock_db = MagicMock()
    mock_db.get_refund_apply_by_card_msg_id.return_value = {
        "status": "expired",
        "order_sn": "260527-006427778640457",
    }

    with (
        patch("database.db_manager.db_manager", mock_db),
        patch("utils.merchant_refund_apply_record.mark_apply_expired"),
    ):
        await handle_mall_system_msg(
            ctx, "570414651", "184046586", send
        )

    send.send_text.assert_not_called()
