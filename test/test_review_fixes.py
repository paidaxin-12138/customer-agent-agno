"""审查修复回归：Consumer 参数顺序、重连 Handler 去重、BuyerLock hold。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import ChannelType, Context, ContextType
from Message.core.consumer import MessageConsumer, MessageConsumerManager
from Message.models.queue_models import MessageWrapper
from utils.buyer_lock_registry import BuyerLockRegistry


def _make_wrapper(**meta_kwargs) -> MessageWrapper:
    ctx = Context(
        type=ContextType.TEXT,
        content="hello",
        channel_type=ChannelType.PINDUODUO,
        kwargs=type(
            "K",
            (),
            {
                "shop_id": "shop1",
                "user_id": "seller1",
                "from_uid": "buyer1",
                "username": "cs",
            },
        )(),
    )
    w = MessageWrapper(message_id="m1", context=ctx, timestamp=0.0)
    return w


@pytest.mark.asyncio
async def test_process_message_calls_prime_metadata_session_with_correct_arg_order():
    consumer = MessageConsumer("test_q", max_concurrent=1)
    consumer.handlers = []
    wrapper = _make_wrapper()

    with patch(
        "database.session_store.prime_metadata_session"
    ) as prime_mock, patch(
        "Agent.CustomerAgent.conversation_memory.prime_session_stage_on_context"
    ), patch(
        "utils.intent_stage_reset.try_intent_stage_reset", return_value=False
    ), patch(
        "utils.inbound_transfer_gate.should_block_handler_until_transfer",
        return_value=False,
    ), patch(
        "Message.handlers.ai_reply_watchdog.start_inbound_watchdog",
        new_callable=AsyncMock,
        return_value=0,
    ):
        await consumer._process_message(wrapper)

    prime_mock.assert_called_once()
    args = prime_mock.call_args[0]
    assert isinstance(args[0], dict), "first arg must be metadata dict"
    assert args[0].get("shop_id") == "shop1"
    assert args[1] is wrapper.context


@pytest.mark.asyncio
async def test_stop_consumer_removes_from_manager_registry():
    mgr = MessageConsumerManager()
    q = "pdd_test_shop_seller"
    mgr.create_consumer(q, max_concurrent=2)
    consumer = mgr.get_consumer(q)
    consumer.handlers = []

    async def _noop(*_a, **_k):
        return False

    class _H:
        def can_handle(self, _ctx):
            return False

        handle = _noop

    consumer.add_handler(_H())
    await mgr.start_consumer(q)
    assert mgr.get_consumer(q) is not None
    await mgr.stop_consumer(q)
    assert mgr.get_consumer(q) is None


@pytest.mark.asyncio
async def test_ws_consumer_setup_does_not_duplicate_handlers_on_recreate():
    from Channel.pinduoduo.ws_consumer_setup import setup_message_consumer
    from Message.core.consumer import message_consumer_manager

    queue_name = "pdd_reconnect_test_q"
    # 清理残留
    if message_consumer_manager.get_consumer(queue_name):
        await message_consumer_manager.stop_consumer(queue_name)

    handlers_chain = [MagicMock(__class__=type("H1", (), {})) for _ in range(3)]
    for i, h in enumerate(handlers_chain):
        h.__class__.__name__ = f"MockHandler{i}"

    with patch(
        "Message.handler_chain_factory.handler_chain", return_value=handlers_chain
    ), patch(
        "core.di_container.container.get", side_effect=Exception("no di")
    ), patch(
        "Agent.CustomerAgent.agent.CustomerAgent"
    ):
        await setup_message_consumer(queue_name)
        first = message_consumer_manager.get_consumer(queue_name)
        assert first is not None
        assert len(first.handlers) == 3
        await message_consumer_manager.stop_consumer(queue_name)

        await setup_message_consumer(queue_name)
        second = message_consumer_manager.get_consumer(queue_name)
        assert second is not None
        assert len(second.handlers) == 3

    await message_consumer_manager.stop_consumer(queue_name)


@pytest.mark.asyncio
async def test_ws_consumer_setup_clears_handlers_when_stop_fails():
    from Channel.pinduoduo.ws_consumer_setup import setup_message_consumer
    from Message.core.consumer import message_consumer_manager

    queue_name = "pdd_stop_fail_test_q"
    if message_consumer_manager.get_consumer(queue_name):
        await message_consumer_manager.stop_consumer(queue_name)

    handlers_chain = [MagicMock(__class__=type("H1", (), {})) for _ in range(2)]
    for i, h in enumerate(handlers_chain):
        h.__class__.__name__ = f"MockHandler{i}"

    with patch(
        "Message.handler_chain_factory.handler_chain", return_value=handlers_chain
    ), patch("core.di_container.container.get", side_effect=Exception("no di")), patch(
        "Agent.CustomerAgent.agent.CustomerAgent"
    ):
        await setup_message_consumer(queue_name)
        consumer = message_consumer_manager.get_consumer(queue_name)
        assert consumer is not None
        assert len(consumer.handlers) == 2
        await message_consumer_manager.stop_consumer(queue_name)

        with patch.object(
            message_consumer_manager,
            "stop_consumer",
            side_effect=RuntimeError("stop failed"),
        ):
            await setup_message_consumer(queue_name)
        again = message_consumer_manager.get_consumer(queue_name)
        assert again is not None
        assert len(again.handlers) == 2

    await message_consumer_manager.stop_consumer(queue_name)


@pytest.mark.asyncio
async def test_ws_consumer_setup_clears_handlers_when_stop_fails():
    from Channel.pinduoduo.ws_consumer_setup import setup_message_consumer
    from Message.core.consumer import message_consumer_manager

    queue_name = "pdd_stop_fail_test_q"
    if message_consumer_manager.get_consumer(queue_name):
        await message_consumer_manager.stop_consumer(queue_name)

    handlers_chain = [MagicMock(__class__=type("H1", (), {})) for _ in range(2)]
    for i, h in enumerate(handlers_chain):
        h.__class__.__name__ = f"MockHandler{i}"

    with patch(
        "Message.handler_chain_factory.handler_chain", return_value=handlers_chain
    ), patch(
        "core.di_container.container.get", side_effect=Exception("no di")
    ), patch(
        "Agent.CustomerAgent.agent.CustomerAgent"
    ), patch.object(
        message_consumer_manager,
        "stop_consumer",
        new_callable=AsyncMock,
        side_effect=RuntimeError("stop failed"),
    ):
        await setup_message_consumer(queue_name)
        first = message_consumer_manager.get_consumer(queue_name)
        assert first is not None
        assert len(first.handlers) == 2

        await setup_message_consumer(queue_name)
        second = message_consumer_manager.get_consumer(queue_name)
        assert second is first
        assert len(second.handlers) == 2

    await message_consumer_manager.stop_consumer(queue_name)


@pytest.mark.asyncio
async def test_buyer_lock_hold_serializes_during_eviction_pressure():
    reg = BuyerLockRegistry(max_keys=100)
    order: list[str] = []

    async def worker(tag: str):
        async with reg.hold("buyer_x"):
            order.append(f"{tag}_start")
            await asyncio.sleep(0.03)
            order.append(f"{tag}_end")

    await asyncio.gather(worker("w1"), worker("w2"))
    assert order.index("w1_start") < order.index("w1_end")
    assert order.index("w2_start") < order.index("w2_end")
    for i in range(0, len(order), 2):
        assert order[i].endswith("_start")
        assert order[i + 1].endswith("_end")
