"""处理器链 mock 上下文集成测试（无 Cookie / WebSocket / MMS）。"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import ChannelType, Context, ContextType
from Message.core.consumer import MessageConsumer
from Message.core.handlers import MessageHandler
from Message.models.queue_models import MessageWrapper


def _make_context(content: str, *, from_uid: str = "buyer_001") -> Context:
    kwargs = type(
        "Kwargs",
        (),
        {
            "from_uid": from_uid,
            "shop_id": "shop_1",
            "user_id": "user_1",
            "username": "test_cs",
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
        message_id="msg-integration-1",
        context=_make_context(content),
        timestamp=0.0,
    )


class _KeywordLikeHandler(MessageHandler):
    """模拟 KeywordDetectionHandler：命中关键词后终止链。"""

    def __init__(self, keyword: str = "转人工"):
        super().__init__()
        self.keyword = keyword
        self.handle_count = 0

    def can_handle(self, context: Context) -> bool:
        text = context.content if isinstance(context.content, str) else ""
        return self.keyword in (text or "")

    async def handle(self, context: Context, metadata: Dict[str, Any]) -> bool:
        self.handle_count += 1
        metadata["_handler_hit"] = self.__class__.__name__
        return True


class _TrailingHandler(MessageHandler):
    """链中后续 Handler，用于断言未被调用。"""

    def __init__(self):
        super().__init__()
        self.handle_count = 0

    def can_handle(self, context: Context) -> bool:
        return True

    async def handle(self, context: Context, metadata: Dict[str, Any]) -> bool:
        self.handle_count += 1
        return True


class _NoOpHandler(MessageHandler):
    """永不处理，用于触发 fallback。"""

    def can_handle(self, context: Context) -> bool:
        return False

    async def handle(self, context: Context, metadata: Dict[str, Any]) -> bool:
        return False


@pytest.fixture
def patch_watchdog():
    with patch(
        "Message.handlers.ai_reply_watchdog.start_inbound_watchdog",
        new_callable=AsyncMock,
        return_value=0,
    ):
        yield


@pytest.mark.asyncio
async def test_handler_chain_stops_on_first_match(patch_watchdog):
    """场景1：首个 Handler 命中后链停止，后续 Handler 不被调用。"""
    consumer = MessageConsumer("integration_q_hit", max_concurrent=1)
    keyword_handler = _KeywordLikeHandler("转人工")
    trailing = _TrailingHandler()
    consumer.handlers = [keyword_handler, trailing]

    wrapper = _make_wrapper("我要转人工")

    with patch.object(
        consumer, "_record_process_failure", MagicMock()
    ) as mock_fail:
        await consumer._process_message(wrapper)

    assert keyword_handler.handle_count == 1
    assert trailing.handle_count == 0
    mock_fail.assert_not_called()


@pytest.mark.asyncio
async def test_handler_chain_fallback_sets_outbound_comfort_sent(patch_watchdog):
    """场景2：无 Handler 处理时触发 fallback_reply，设置 _outbound_comfort_sent。"""
    consumer = MessageConsumer("integration_q_fallback", max_concurrent=1)
    consumer.handlers = [_NoOpHandler()]

    wrapper = _make_wrapper("随便聊聊")
    captured_metadata: List[Dict[str, Any]] = []

    async def _fake_send(*args, **kwargs):
        meta = kwargs.get("metadata")
        if meta is not None:
            meta["_outbound_comfort_sent"] = True
            captured_metadata.append(meta)
        return True

    with patch(
        "Message.handlers.fallback_reply.config.get",
        lambda key, default=None: True
        if key == "chat.unhandled_fallback_enabled"
        else default,
    ), patch(
        "Message.handlers.channel_send.send_text_to_buyer",
        side_effect=_fake_send,
    ), patch.object(consumer, "_record_process_failure", MagicMock()) as mock_fail:
        await consumer._process_message(wrapper)

    assert captured_metadata, "fallback 应调用 send_text_to_buyer"
    assert captured_metadata[0].get("_outbound_comfort_sent") is True
    mock_fail.assert_not_called()
