"""TurnAborted 时静默跳过：不发兜底话术、取消 inbound watchdog。"""
from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import ChannelType, Context, ContextType, PinduoduoKwargs
from core.turn_abort import TurnAborted


def _ai_context() -> Context:
    return Context(
        type=ContextType.TEXT,
        content="你好",
        channel_type=ChannelType.PINDUODUO,
        kwargs=PinduoduoKwargs(
            shop_name="s",
            shop_id="1",
            user_id="u",
            from_uid="b",
        ),
    )


def _enter_ai_handler_patches(stack: ExitStack, handler):
    stack.enter_context(
        patch.object(
            handler, "_is_ai_mode_enabled", new_callable=AsyncMock, return_value=True
        )
    )
    stack.enter_context(
        patch.object(handler, "_get_session_key", return_value="1/u/b")
    )
    tracker_mock = stack.enter_context(
        patch("Message.handlers.ai_handler.get_ai_queue_tracker")
    )
    stack.enter_context(patch("Message.handlers.ai_handler.is_escalated", return_value=False))
    send_mock = stack.enter_context(
        patch.object(handler, "_send_reply", new_callable=AsyncMock, return_value=True)
    )
    fallback_mock = stack.enter_context(
        patch.object(
            handler,
            "_handle_unknown_ai_failure",
            new_callable=AsyncMock,
            return_value=True,
        )
    )
    tracker_mock.return_value.should_queue_degrade.return_value = False
    tracker_mock.return_value.ai_inflight.return_value.__aenter__ = AsyncMock(
        return_value=None
    )
    tracker_mock.return_value.ai_inflight.return_value.__aexit__ = AsyncMock(
        return_value=None
    )
    return send_mock, fallback_mock


@pytest.mark.asyncio
async def test_turn_aborted_arun_timeout_uses_fallback():
    from Message.handlers.ai_handler import AIReplyHandler

    handler = AIReplyHandler()
    ctx = _ai_context()
    metadata: dict = {"shop_id": "1", "user_id": "u", "from_uid": "b", "_watchdog_epoch": 2}

    with ExitStack() as stack:
        send_mock, fallback_mock = _enter_ai_handler_patches(stack, handler)
        stack.enter_context(
            patch(
                "Message.handlers.ai_handler.turn_abort_registry.begin_turn",
                return_value=MagicMock(turn_id="t1"),
            )
        )
        stack.enter_context(
            patch.object(
                handler,
                "_get_ai_reply_with_sync_retry",
                new_callable=AsyncMock,
                side_effect=TurnAborted("arun_timeout", "t1"),
            )
        )
        notify_mock = stack.enter_context(
            patch("Message.handlers.channel_send.notify_outbound_from_metadata")
        )
        ok = await handler.handle(ctx, metadata)

    assert ok is True
    fallback_mock.assert_called_once()
    assert fallback_mock.call_args.args[5] == "ai_timeout"
    send_mock.assert_not_called()
    notify_mock.assert_not_called()


@pytest.mark.asyncio
async def test_turn_aborted_silent_skips_watchdog_when_no_epoch():
    from Message.handlers.ai_handler import AIReplyHandler

    handler = AIReplyHandler()
    ctx = _ai_context()
    metadata: dict = {"shop_id": "1", "user_id": "u", "from_uid": "b"}

    with ExitStack() as stack:
        _, fallback_mock = _enter_ai_handler_patches(stack, handler)
        stack.enter_context(
            patch(
                "Message.handlers.ai_handler.turn_abort_registry.begin_turn",
                return_value=MagicMock(turn_id="t2"),
            )
        )
        stack.enter_context(
            patch.object(
                handler,
                "_get_ai_reply_with_sync_retry",
                new_callable=AsyncMock,
                side_effect=TurnAborted("superseded_by_new_inbound", "t2"),
            )
        )
        notify_mock = stack.enter_context(
            patch("Message.handlers.channel_send.notify_outbound_from_metadata")
        )
        ok = await handler.handle(ctx, metadata)

    assert ok is True
    fallback_mock.assert_not_called()
    notify_mock.assert_not_called()
    assert metadata.get("_turn_aborted") == "superseded_by_new_inbound"
