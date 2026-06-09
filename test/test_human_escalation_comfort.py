# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""转人工安抚话术：检测即发送 + 弹窗关闭补发。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import Context, ContextType
from utils.human_escalation_comfort import (
    human_transfer_comfort_notice,
    resolve_session_ids,
    send_human_transfer_comfort,
    send_human_transfer_comfort_from_payload,
    should_send_dialog_comfort_on_dismiss,
)


def _ctx(**kwargs):
    ku = MagicMock()
    for k, v in kwargs.items():
        setattr(ku, k, v)
    ctx = Context(type=ContextType.TEXT, content="转人工", kwargs=ku)
    return ctx


def test_resolve_session_ids_prefers_metadata():
    ctx = _ctx(shop_id="s_kw", user_id="u_kw", from_uid="b_kw")
    meta = {"shop_id": "s_meta", "user_id": "u_meta", "from_uid": "b_meta"}
    assert resolve_session_ids(ctx, meta) == ("s_meta", "u_meta", "b_meta")


def test_resolve_session_ids_falls_back_to_kwargs():
    ctx = _ctx(shop_id="s1", user_id="u1", from_uid="b1")
    assert resolve_session_ids(ctx, {}) == ("s1", "u1", "b1")


@pytest.mark.asyncio
async def test_send_human_transfer_comfort_skips_when_already_sent():
    meta = {
        "shop_id": "s",
        "user_id": "u",
        "from_uid": "b",
        "_outbound_comfort_sent": True,
    }
    ctx = _ctx()
    with patch(
        "Message.handlers.channel_send.send_text_to_buyer",
        new_callable=AsyncMock,
    ) as mock_send:
        ok = await send_human_transfer_comfort(ctx, meta, reason="keyword_human")
    assert ok is False
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_send_human_transfer_comfort_sends_notice():
    meta = {"shop_id": "s", "user_id": "u", "from_uid": "b"}
    ctx = _ctx()
    with patch(
        "Message.handlers.channel_send.send_text_to_buyer",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_send:
        ok = await send_human_transfer_comfort(ctx, meta, reason="keyword_human")
    assert ok is True
    mock_send.assert_awaited_once()
    args = mock_send.await_args.args
    assert args[3] == human_transfer_comfort_notice()


def test_send_comfort_from_payload_skips_when_comfort_sent():
    payload = {
        "reason": "keyword_human",
        "comfort_sent": True,
        "platform_shop_id": "s",
        "seller_user_id": "u",
        "buyer_uid": "b",
    }
    with patch(
        "Channel.pinduoduo.utils.API.send_message.SendMessage"
    ) as mock_cls:
        ok = send_human_transfer_comfort_from_payload(payload)
    assert ok is False
    mock_cls.assert_not_called()


def test_send_comfort_from_payload_on_dismiss():
    payload = {
        "reason": "keyword_human",
        "comfort_sent": False,
        "platform_shop_id": "s",
        "seller_user_id": "u",
        "buyer_uid": "b",
    }
    mock_sender = MagicMock()
    mock_sender.send_text.return_value = {"success": True}
    with patch(
        "Channel.pinduoduo.utils.API.send_message.SendMessage",
        return_value=mock_sender,
    ):
        ok = send_human_transfer_comfort_from_payload(payload)
    assert ok is True
    mock_sender.send_text.assert_called_once_with("b", human_transfer_comfort_notice())


def test_should_send_dialog_comfort_on_dismiss():
    assert should_send_dialog_comfort_on_dismiss("keyword_human")
    assert not should_send_dialog_comfort_on_dismiss("media_human")


@pytest.mark.asyncio
async def test_keyword_handler_sends_comfort_before_emit():
    from Message.handlers.keyword_handler import KeywordDetectionHandler

    handler = KeywordDetectionHandler()
    ctx = _ctx(shop_id="s", user_id="u", from_uid="b")
    ctx.content = "转人工"
    meta = {"shop_id": "s", "user_id": "u", "from_uid": "b"}

    with patch(
        "Message.handlers.keyword_handler.send_human_transfer_comfort",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_comfort, patch(
        "core.human_assist_bus.emit_human_assist",
    ) as mock_emit, patch(
        "Message.handlers.keyword_handler.transfer_to_available_cs_async",
        new_callable=AsyncMock,
        return_value=False,
    ), patch(
        "Message.handlers.keyword_handler.send_text_to_buyer",
        new_callable=AsyncMock,
        return_value=True,
    ):
        handled = await handler.handle(ctx, meta)

    assert handled is True
    mock_comfort.assert_awaited_once()
    mock_emit.assert_called_once()
    assert mock_comfort.await_args_list[0].kwargs.get("reason") == "keyword_human"
