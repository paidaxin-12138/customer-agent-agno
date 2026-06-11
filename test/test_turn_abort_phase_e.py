"""Turn Abort Phase E：入队层 supersede + 慢 arun 集成。"""
from __future__ import annotations

import asyncio
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import ChannelType, Context, ContextType
from core.turn_abort import TurnAbortRegistry, turn_abort_registry


def _ctx(content: str, *, buyer: str = "buyer_1") -> Context:
    kwargs = type(
        "Kwargs",
        (),
        {
            "from_uid": buyer,
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


def _session_key() -> str:
    return "pinduoduo:shop_1:user_1:buyer_1"


def test_resolve_session_key_from_context_kwargs_only():
    from Message.handlers.ai_reply_watchdog import resolve_session_key

    assert resolve_session_key(context=_ctx("hi")) == _session_key()


def test_abort_active_turn_aborts_without_beginning_new():
    reg = TurnAbortRegistry()
    sig = reg.begin_turn("s/u/b")
    assert sig is not None
    assert reg.abort_active_turn("s/u/b", "superseded_by_new_inbound") is True
    assert sig.is_aborted()
    assert reg.abort_active_turn("s/u/b", "again") is False


def test_maybe_supersede_turn_on_enqueue_aborts_active():
    from core.turn_abort import maybe_supersede_turn_on_enqueue

    reg = TurnAbortRegistry()
    sig = reg.begin_turn(_session_key())
    assert sig is not None

    with patch("core.turn_abort.turn_abort_registry", reg), patch(
        "core.turn_abort._turn_abort_enabled", return_value=True
    ), patch("core.turn_abort._turn_abort_supersede_on_new_inbound", return_value=True):
        maybe_supersede_turn_on_enqueue(_ctx("第二条"))

    assert sig.is_aborted()
    assert sig.reason() == "superseded_by_new_inbound"


@pytest.mark.asyncio
async def test_put_message_supersedes_active_turn_on_enqueue():
    from Message import put_message

    reg = TurnAbortRegistry()
    sig = reg.begin_turn(_session_key())
    assert sig is not None

    with patch("core.turn_abort.turn_abort_registry", reg), patch(
        "core.turn_abort._turn_abort_enabled", return_value=True
    ), patch("core.turn_abort._turn_abort_supersede_on_new_inbound", return_value=True), patch(
        "Message.core.queue.SimpleMessageQueue.put", new_callable=AsyncMock, return_value="m2"
    ):
        msg_id = await put_message("phase_e_q", _ctx("follow-up"))

    assert msg_id == "m2"
    assert sig.is_aborted()
    assert sig.reason() == "superseded_by_new_inbound"


def _patch_ai_handler(handler):
    stack = ExitStack()
    stack.enter_context(
        patch.object(
            handler, "_is_ai_mode_enabled", new_callable=AsyncMock, return_value=True
        )
    )
    stack.enter_context(
        patch.object(handler, "_get_session_key", return_value=_session_key())
    )
    tracker_mock = stack.enter_context(
        patch("Message.handlers.ai_handler.get_ai_queue_tracker")
    )
    stack.enter_context(patch("Message.handlers.ai_handler.is_escalated", return_value=False))
    stack.enter_context(
        patch(
            "Message.handlers.ai_handler.sanitize_ai_reply_content",
            side_effect=lambda x: x,
        )
    )
    send_mock = stack.enter_context(
        patch.object(handler, "_send_reply", new_callable=AsyncMock, return_value=True)
    )
    tracker_mock.return_value.should_queue_degrade.return_value = False
    tracker_mock.return_value.ai_inflight.return_value.__aenter__ = AsyncMock(
        return_value=None
    )
    tracker_mock.return_value.ai_inflight.return_value.__aexit__ = AsyncMock(
        return_value=None
    )
    return stack, send_mock


@pytest.mark.asyncio
async def test_slow_first_turn_aborted_by_second_enqueue_no_outbound():
    from Message import put_message
    from Message.handlers.ai_handler import AIReplyHandler
    from Message.core.consumer import MessageConsumer

    handler = AIReplyHandler()
    consumer = MessageConsumer("phase_e_slow_q", max_concurrent=2)
    consumer.handlers = [handler]

    first_in_ai = asyncio.Event()
    calls = {"n": 0}

    async def _ai_reply(query, context, metadata):
        calls["n"] += 1
        if calls["n"] == 1:
            first_in_ai.set()
            while True:
                sig = turn_abort_registry.get_active(_session_key())
                if sig is not None:
                    sig.check()
                await asyncio.sleep(0.01)
        return "second-reply"

    stack, send_mock = _patch_ai_handler(handler)
    with stack, patch.object(
        handler, "_get_ai_reply_with_sync_retry", side_effect=_ai_reply
    ), patch(
        "database.session_store.prime_metadata_session", return_value=None
    ), patch(
        "Agent.CustomerAgent.conversation_memory.prime_session_stage_on_context",
        return_value=None,
    ), patch(
        "utils.intent_stage_reset.try_intent_stage_reset", return_value=False
    ), patch(
        "utils.inbound_transfer_gate.should_block_handler_until_transfer",
        return_value=False,
    ), patch(
        "Message.handlers.ai_reply_watchdog.start_inbound_watchdog",
        new_callable=AsyncMock,
        return_value=0,
    ), patch(
        "Message.handlers.channel_send.notify_outbound_from_metadata"
    ):
        await consumer.start()
        t1 = asyncio.create_task(put_message(consumer.queue_name, _ctx("first")))
        await asyncio.wait_for(first_in_ai.wait(), timeout=3)
        t2 = asyncio.create_task(put_message(consumer.queue_name, _ctx("second")))
        await asyncio.gather(t1, t2)
        await asyncio.sleep(0.3)
        await consumer.stop()

    assert calls["n"] == 2
    assert send_mock.call_count == 1
    assert send_mock.call_args[0][1] == "second-reply"
