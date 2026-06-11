"""Turn Abort Phase 1 TDD。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import ChannelType, Context, ContextType, PinduoduoKwargs
from core.turn_abort import (
    TurnAborted,
    TurnAbortRegistry,
    get_current_turn_abort,
    reset_current_turn_abort,
    set_current_turn_abort,
    turn_abort_registry,
)


def test_begin_turn_increments_epoch():
    reg = TurnAbortRegistry()
    s1 = reg.begin_turn("shop/u/b")
    s2 = reg.begin_turn("shop/u/b")
    assert s1 is not None and s2 is not None
    assert s1.epoch == 1
    assert s2.epoch == 2
    assert s1.turn_id != s2.turn_id


def test_begin_turn_supersedes_previous_signal():
    reg = TurnAbortRegistry()
    old = reg.begin_turn("s/u/b")
    assert old is not None
    new = reg.begin_turn("s/u/b")
    assert old.is_aborted()
    assert old.reason() == "superseded_by_new_inbound"
    assert new is not None
    assert not new.is_aborted()


def test_check_turn_abort_raises():
    reg = TurnAbortRegistry()
    sig = reg.begin_turn("s/u/b")
    sig.abort("test")
    with pytest.raises(TurnAborted) as exc:
        sig.check()
    assert exc.value.reason == "test"


def test_contextvar_propagation():
    reg = TurnAbortRegistry()
    sig = reg.begin_turn("s/u/b")
    tok = set_current_turn_abort(sig)
    try:
        assert get_current_turn_abort() is sig
    finally:
        reset_current_turn_abort(tok)
    assert get_current_turn_abort() is None


@pytest.mark.asyncio
async def test_async_reply_drops_stale_result_when_aborted():
    from Agent.CustomerAgent.agent import CustomerAgent

    agent = CustomerAgent(knowledge_manager=MagicMock())
    agent._agent = MagicMock()
    agent._is_initialized = True

    reg = TurnAbortRegistry()
    signal = reg.begin_turn("1/u/b")
    reg.abort_turn(signal.turn_id, "superseded_by_new_inbound")

    run_output = MagicMock()
    run_output.content = "迟到回复"

    loop = asyncio.get_running_loop()

    def _fake_run_in_executor(executor, fn, *args):
        fut = loop.create_future()
        fut.set_result(fn(*args))
        return fut

    tok = set_current_turn_abort(signal)
    try:
        with patch.object(
            loop, "run_in_executor", side_effect=_fake_run_in_executor
        ), patch.object(
            agent, "_run_agent_arun_blocking", return_value=run_output
        ), patch.object(agent, "_build_input_with_transcript", return_value="q"), patch(
            "Agent.CustomerAgent.agent.set_platform_shop_context",
            return_value=MagicMock(),
        ), patch("Agent.CustomerAgent.agent.reset_platform_shop_context"):
            ctx = Context(
                type=ContextType.TEXT,
                content="q",
                channel_type=ChannelType.PINDUODUO,
                kwargs=PinduoduoKwargs(
                    shop_name="s",
                    shop_id="1",
                    user_id="u",
                    from_uid="b",
                ),
            )
            with pytest.raises(TurnAborted):
                await agent.async_reply("q", ctx)
    finally:
        reset_current_turn_abort(tok)


@pytest.mark.asyncio
async def test_async_reply_aborts_signal_on_timeout():
    from Agent.CustomerAgent.agent import CustomerAgent

    agent = CustomerAgent(knowledge_manager=MagicMock())
    agent._agent = MagicMock()
    agent._is_initialized = True

    reg = TurnAbortRegistry()
    signal = reg.begin_turn("1/u/b")

    loop = asyncio.get_running_loop()

    async def _slow_executor(executor, fn, *args):
        await asyncio.sleep(5)
        return MagicMock(content="late")

    tok = set_current_turn_abort(signal)
    try:
        with patch.object(
            loop, "run_in_executor", side_effect=_slow_executor
        ), patch.object(agent, "_build_input_with_transcript", return_value="q"), patch(
            "Agent.CustomerAgent.agent._llm_arun_timeout_sec", return_value=0.05
        ), patch(
            "Agent.CustomerAgent.agent.set_platform_shop_context",
            return_value=MagicMock(),
        ), patch("Agent.CustomerAgent.agent.reset_platform_shop_context"):
            ctx = Context(
                type=ContextType.TEXT,
                content="q",
                channel_type=ChannelType.PINDUODUO,
                kwargs=PinduoduoKwargs(
                    shop_name="s",
                    shop_id="1",
                    user_id="u",
                    from_uid="b",
                ),
            )
            with pytest.raises(TurnAborted) as exc:
                await agent.async_reply("q", ctx)
    finally:
        reset_current_turn_abort(tok)

    assert signal.is_aborted()
    assert exc.value.reason == "arun_timeout"


def test_turn_abort_disabled_returns_none(monkeypatch):
    monkeypatch.setenv("TURN_ABORT_TEST", "1")
    reg = TurnAbortRegistry()
    with patch("core.turn_abort._turn_abort_enabled", return_value=False):
        assert reg.begin_turn("s/u/b") is None


@pytest.mark.asyncio
async def test_ai_handler_begins_turn_before_llm_call():
    from Message.handlers.ai_handler import AIReplyHandler

    handler = AIReplyHandler()
    handler.bot = MagicMock()
    handler.bot.async_reply = AsyncMock(return_value=MagicMock(content="ok"))

    ctx = Context(
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
    metadata: dict = {
        "shop_id": "1",
        "user_id": "u",
        "from_uid": "b",
        "_watchdog_epoch": 1,
    }

    begun: dict = {}

    real_begin = turn_abort_registry.begin_turn

    def _track_begin(session_key: str):
        sig = real_begin(session_key)
        begun["signal"] = sig
        return sig

    with patch.object(
        handler, "_is_ai_mode_enabled", new_callable=AsyncMock, return_value=True
    ), patch.object(
        handler, "_get_session_key", return_value="1/u/b"
    ), patch(
        "Message.handlers.ai_handler.turn_abort_registry.begin_turn",
        side_effect=_track_begin,
    ), patch.object(
        handler, "_send_reply", new_callable=AsyncMock, return_value=True
    ), patch(
        "Message.handlers.ai_handler.get_ai_queue_tracker"
    ) as tracker_mock, patch(
        "Message.handlers.ai_handler.is_escalated", return_value=False
    ), patch(
        "Message.handlers.ai_handler.sanitize_ai_reply_content",
        side_effect=lambda x: x,
    ), patch.object(
        handler, "_get_ai_reply_with_sync_retry", new_callable=AsyncMock, return_value="ok"
    ):
        tracker_mock.return_value.should_queue_degrade.return_value = False
        tracker_mock.return_value.ai_inflight.return_value.__aenter__ = AsyncMock(
            return_value=None
        )
        tracker_mock.return_value.ai_inflight.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        await handler.handle(ctx, metadata)

    assert begun.get("signal") is not None
    assert metadata.get("_turn_id") == begun["signal"].turn_id
