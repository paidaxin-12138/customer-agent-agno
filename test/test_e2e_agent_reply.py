# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""端到端：AIReplyHandler 生成回复、出站并落库（mock WS/MMS/LLM）。"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import ChannelType, Context, ContextType
from bridge.reply import Reply
from Message.handlers.ai_handler import AIReplyHandler


class _MockBot:
    def reply(self, query: str, context: Context) -> Reply:
        return Reply(content=f"您好，关于「{query}」已为您查询。")


def _make_context(content: str = "发货了吗") -> Context:
    kwargs = type(
        "Kwargs",
        (),
        {
            "from_uid": "buyer_e2e_ai",
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


def _metadata() -> Dict[str, Any]:
    return {
        "shop_id": "shop_e2e",
        "user_id": "user_e2e",
        "from_uid": "buyer_e2e_ai",
        "username": "cs_e2e",
        "channel_name": "pinduoduo",
        "session_id": 42,
        "account_id": 7,
    }


@pytest.fixture
def ai_handler_patches():
    persisted: List[tuple] = []
    mock_sender = MagicMock()
    mock_sender.send_text.return_value = {"success": True}

    def _capture_persist(*args, **kwargs):
        persisted.append((args, kwargs))

    with patch(
        "utils.ai_mode_check.is_ai_mode_enabled", return_value=True
    ), patch(
        "Message.handlers.ai_handler.is_escalated", return_value=False
    ), patch(
        "Message.handlers.ai_handler.get_ai_queue_tracker"
    ) as mock_tracker_cls, patch(
        "Message.handlers.ai_reply_watchdog.resolve_session_key",
        return_value="pinduoduo_shop_e2e_buyer_e2e_ai",
    ), patch(
        "Agent.CustomerAgent.conversation_memory.get_current_stage",
        return_value="idle",
    ), patch(
        "Channel.pinduoduo.utils.API.send_message.SendMessage",
        return_value=mock_sender,
    ), patch(
        "database.chat_persist.persist_ai_message",
        side_effect=_capture_persist,
    ), patch(
        "utils.inbound_transfer_gate.should_block_handler_until_transfer",
        return_value=False,
    ):
        tracker = MagicMock()
        tracker.should_queue_degrade.return_value = False
        tracker.ai_inflight.return_value.__aenter__ = AsyncMock(return_value=None)
        tracker.ai_inflight.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_tracker_cls.return_value = tracker
        yield persisted, mock_sender


@pytest.mark.asyncio
async def test_e2e_ai_reply_handler_sends_and_persists(ai_handler_patches):
    persisted, mock_sender = ai_handler_patches
    handler = AIReplyHandler(bot=_MockBot())
    ctx = _make_context("我的货发货了吗")
    meta = _metadata()

    ok = await handler.handle(ctx, meta)

    assert ok is True
    mock_sender.send_text.assert_called_once()
    args, _kwargs = mock_sender.send_text.call_args
    assert args[0] == "buyer_e2e_ai"
    assert "发货" in args[1] or "查询" in args[1]
    assert len(persisted) == 1
    persist_args = persisted[0][0]
    assert persist_args[4] == "buyer_e2e_ai"
    assert handler._stats["ai_ok"] >= 1
