"""WebSocket 入站 pipeline 单测。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import ChannelType, Context, ContextType
from Channel.pinduoduo.pdd_message import PDDChatMessage
from Channel.pinduoduo.ws_inbound_pipeline import (
    dispatch_inbound_message,
    log_transfer_buyer_mismatch,
    preprocess_inbound_context,
    process_inbound_ws_frame,
)


def _kwargs(**overrides):
    base = {
        "from_user": "user",
        "from_uid": "buyer-1",
        "to_uid": "seller-1",
        "shop_id": "570414651",
        "user_id": "184046586",
    }
    base.update(overrides)
    return type("K", (), base)()


def test_preprocess_records_hub():
    ctx = Context(
        type=ContextType.TEXT,
        content="你好",
        channel_type=ChannelType.PINDUODUO,
        kwargs=_kwargs(),
    )
    record = MagicMock()
    with patch(
        "core.conversation_record.record_inbound_from_context",
        record,
    ), patch(
        "utils.platform_system_msg.is_platform_civility_message",
        return_value=False,
    ):
        preprocess_inbound_context(
            ctx,
            channel_name="pinduoduo",
            shop_id="570414651",
            user_id="184046586",
            username="shop1",
        )
    record.assert_called_once()


def test_log_transfer_buyer_mismatch():
    ctx = Context(
        type=ContextType.TEXT,
        content="hi",
        channel_type=ChannelType.PINDUODUO,
        kwargs=_kwargs(to_uid="other-seller"),
    )
    log = MagicMock()
    log_transfer_buyer_mismatch(ctx, user_id="184046586", logger=log)
    log.info.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_queues_text_message():
    ctx = Context(
        type=ContextType.TEXT,
        content="问题",
        channel_type=ChannelType.PINDUODUO,
        kwargs=_kwargs(),
    )
    pdd = PDDChatMessage({"message": {"type": 0, "content": "问题"}})
    pdd.msg_id = "m1"
    put = AsyncMock(return_value="wrap-1")

    with patch(
        "Channel.pinduoduo.ws_inbound_pipeline.handle_immediate_message",
        new_callable=AsyncMock,
    ) as immediate:
        await dispatch_inbound_message(
            ctx,
            pdd,
            channel_name="pinduoduo",
            shop_id="570414651",
            user_id="184046586",
            username="shop1",
            queue_name="pdd_570414651",
            ws_connections={},
            put_message=put,
        )

    immediate.assert_not_awaited()
    put.assert_awaited_once_with("pdd_570414651", ctx)


@pytest.mark.asyncio
async def test_dispatch_immediate_transfer():
    ctx = Context(
        type=ContextType.TRANSFER,
        content='{"to_uid":"4216881609"}',
        channel_type=ChannelType.PINDUODUO,
        kwargs=_kwargs(from_user="system"),
    )
    pdd = PDDChatMessage({"response": "push"})
    pdd.msg_id = "t1"
    put = AsyncMock()
    immediate = AsyncMock()

    with patch(
        "Channel.pinduoduo.ws_inbound_pipeline.handle_immediate_message",
        immediate,
    ):
        await dispatch_inbound_message(
            ctx,
            pdd,
            channel_name="pinduoduo",
            shop_id="570414651",
            user_id="184046586",
            username="shop1",
            queue_name="pdd_570414651",
            ws_connections={"570414651_184046586": MagicMock()},
            put_message=put,
        )

    immediate.assert_awaited_once()
    put.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_inbound_ws_frame_end_to_end():
    raw = '{"response":"push","message":{"type":0,"content":"你好","from":{"role":"user","uid":"buyer-1"},"to":{"uid":"seller-1"}}}'
    put = AsyncMock(return_value="w1")
    record = MagicMock()

    with (
        patch(
            "core.conversation_record.record_inbound_from_context",
            record,
        ),
        patch(
            "utils.platform_system_msg.is_platform_civility_message",
            return_value=False,
        ),
        patch("database.db_manager.db_manager.get_shop", return_value={"shop_name": "店"}),
        patch(
            "database.chat_persist.persist_customer_from_context",
            return_value=1,
        ),
    ):
        await process_inbound_ws_frame(
            raw,
            channel_name="pinduoduo",
            shop_id="570414651",
            user_id="184046586",
            username="shop1",
            queue_name="pdd_570414651",
            ws_connections={},
            put_message=put,
        )

    record.assert_called_once()
    put.assert_awaited_once()
