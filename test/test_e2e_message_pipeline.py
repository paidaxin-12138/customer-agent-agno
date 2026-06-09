# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""端到端消息管道：入队 → 消费者 → Handler → MMS 出站（无真实 WS/Cookie）。"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import ChannelType, Context, ContextType
from Message.core.consumer import MessageConsumer
from Message.core.handlers import MessageHandler
from Message.core.queue import queue_manager
from Message.handlers.channel_send import send_text_to_buyer
from Message.models.queue_models import MessageWrapper, QueueConfig


def _make_context(content: str, *, from_uid: str = "buyer_e2e") -> Context:
    kwargs = type(
        "Kwargs",
        (),
        {
            "from_uid": from_uid,
            "shop_id": "shop_e2e",
            "user_id": "user_e2e",
            "username": "cs_e2e",
        },
    )()
    return Context(
        type=ContextType.TEXT,
        content=content,
        channel_type=ChannelType.PINDUODUO,
        kwargs=kwargs,
    )


def _make_wrapper(content: str) -> MessageWrapper:
    return MessageWrapper(
        message_id="msg-e2e-1",
        context=_make_context(content),
        timestamp=0.0,
    )


class _AutoReplyHandler(MessageHandler):
    """模拟 AI/关键词 Handler：命中后调用 send_text_to_buyer。"""

    def __init__(self, trigger: str = "发货"):
        super().__init__()
        self.trigger = trigger
        self.handle_count = 0

    def can_handle(self, context: Context) -> bool:
        text = context.content if isinstance(context.content, str) else ""
        return self.trigger in (text or "")

    async def handle(self, context: Context, metadata: Dict[str, Any]) -> bool:
        self.handle_count += 1
        ku = getattr(context, "kwargs", None)
        return await send_text_to_buyer(
            getattr(ku, "shop_id", ""),
            getattr(ku, "user_id", ""),
            getattr(ku, "from_uid", ""),
            "您好，物流已发出，请留意签收。",
            context=context,
            metadata=metadata,
        )


@pytest.fixture
def patch_pipeline_deps():
    with patch(
        "Message.handlers.ai_reply_watchdog.start_inbound_watchdog",
        new_callable=AsyncMock,
        return_value=0,
    ), patch(
        "utils.inbound_transfer_gate.should_block_handler_until_transfer",
        return_value=False,
    ):
        yield


@pytest.mark.asyncio
async def test_e2e_handler_outbound_via_send_message(patch_pipeline_deps):
    """Handler 处理 → channel_send → SendMessage.send_text（mock MMS）。"""
    consumer = MessageConsumer("e2e_outbound", max_concurrent=1)
    handler = _AutoReplyHandler("发货")
    consumer.handlers = [handler]
    wrapper = _make_wrapper("我的货发货了吗")

    mock_sender = MagicMock()
    mock_sender.send_text.return_value = {"success": True}

    with patch(
        "Channel.pinduoduo.utils.API.send_message.SendMessage",
        return_value=mock_sender,
    ), patch.object(consumer, "_record_process_failure", MagicMock()) as mock_fail:
        await consumer._process_message(wrapper)

    assert handler.handle_count == 1
    mock_sender.send_text.assert_called_once_with(
        "buyer_e2e", "您好，物流已发出，请留意签收。"
    )
    mock_fail.assert_not_called()


@pytest.mark.asyncio
async def test_e2e_queue_to_consumer_outbound(patch_pipeline_deps):
    """SimpleMessageQueue.put → Consumer worker → Handler → 出站。"""
    queue_name = "e2e_queue_pipe"
    queue_manager._queues.pop(queue_name, None)

    queue = queue_manager.get_or_create_queue(
        queue_name, QueueConfig(max_size=32, enable_deduplication=False)
    )
    consumer = MessageConsumer(queue_name, max_concurrent=1)
    handler = _AutoReplyHandler("查询")
    consumer.handlers = [handler]

    mock_sender = MagicMock()
    mock_sender.send_text.return_value = {"success": True}
    done = asyncio.Event()

    def _mark_done(*args, **kwargs):
        done.set()
        return {"success": True}

    mock_sender.send_text.side_effect = _mark_done

    with patch(
        "Channel.pinduoduo.utils.API.send_message.SendMessage",
        return_value=mock_sender,
    ):
        await consumer.start()
        try:
            ctx = _make_context("帮我查询一下物流")
            await queue.put(ctx)
            await asyncio.wait_for(done.wait(), timeout=3.0)
        finally:
            await consumer.stop()

    assert handler.handle_count == 1
    mock_sender.send_text.assert_called_once()
