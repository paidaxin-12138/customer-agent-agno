"""P2 审查修复回归测试。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import ChannelType, Context, ContextType
from core.connection_status import ConnectionState, ConnectionStatus


def test_evaluate_readiness_requires_all_connected_by_default(monkeypatch):
    from core.health_server import _evaluate_readiness

    s1 = ConnectionStatus("s1", "u1", "a", ConnectionState.CONNECTED)
    s2 = ConnectionStatus("s2", "u2", "b", ConnectionState.CONNECTED)

    class _Mgr:
        def get_all_status(self):
            return [s1, s2]

    running_consumer = MagicMock()
    running_consumer.is_running.return_value = True

    class _ConsumerMgr:
        def get_consumer(self, name):
            if name.endswith("s1_u1"):
                return running_consumer
            return None

    monkeypatch.setattr("core.connection_status.ConnectionStatusManager", lambda: _Mgr())
    monkeypatch.setattr(
        "Message.core.consumer.message_consumer_manager",
        _ConsumerMgr(),
    )
    ready, reason, detail = _evaluate_readiness()
    assert ready is False
    assert reason == "not_all_connected_shops_ready"
    assert len(detail["consumers_not_ready"]) == 1


def test_evaluate_readiness_legacy_any_one(monkeypatch):
    from core.health_server import _evaluate_readiness

    monkeypatch.setenv("READINESS_REQUIRE_ALL_CONNECTED", "0")
    s1 = ConnectionStatus("s1", "u1", "a", ConnectionState.CONNECTED)
    s2 = ConnectionStatus("s2", "u2", "b", ConnectionState.CONNECTED)

    class _Mgr:
        def get_all_status(self):
            return [s1, s2]

    running_consumer = MagicMock()
    running_consumer.is_running.return_value = True

    class _ConsumerMgr:
        def get_consumer(self, name):
            if name.endswith("s1_u1"):
                return running_consumer
            return None

    monkeypatch.setattr("core.connection_status.ConnectionStatusManager", lambda: _Mgr())
    monkeypatch.setattr(
        "Message.core.consumer.message_consumer_manager",
        _ConsumerMgr(),
    )
    ready, reason, _ = _evaluate_readiness()
    assert ready is True
    assert reason == ""


def test_hub_skips_memory_update_when_persist_fails():
    from ui.conversation_hub import ConversationHub
    from bridge.context import PinduoduoKwargs

    hub = ConversationHub()
    ctx = Context(
        type=ContextType.TEXT,
        content="买家消息",
        channel_type=ChannelType.PINDUODUO,
        kwargs=PinduoduoKwargs(
            from_user="user",
            from_uid="buyer_x",
            nickname="买家X",
            shop_id="s1",
            user_id="u1",
            msg_id="m1",
        ),
    )
    with patch(
        "database.chat_persist.persist_customer_from_context",
        side_effect=RuntimeError("db down"),
    ), patch.object(hub, "_sync_from_db") as mock_sync, patch.object(
        hub, "_refresh_or_touch"
    ) as mock_touch, patch(
        "utils.qt_threading.run_on_main_thread", side_effect=lambda fn: fn()
    ):
        hub.record_from_context("pinduoduo", "s1", "u1", "cs", ctx)

    mock_sync.assert_not_called()
    mock_touch.assert_not_called()


@pytest.mark.asyncio
async def test_put_message_retries_on_full_queue(monkeypatch):
    from Message import put_message
    from Message.core.queue import queue_manager

    queue_name = "test_put_retry_q"
    if queue_name in queue_manager._queues:
        queue_manager._queues.pop(queue_name)

    ctx = Context(
        type=ContextType.TEXT,
        content="hi",
        channel_type=ChannelType.PINDUODUO,
    )
    queue = queue_manager.get_or_create_queue(queue_name)
    from Message.models.queue_models import QueueConfig

    queue_manager._queues[queue_name] = type(queue)(
        queue_name, QueueConfig(max_size=1, enable_deduplication=False)
    )
    queue = queue_manager._queues[queue_name]

    # 填满队列
    await queue.put(ctx)
    assert queue.size() == 1

    calls = {"n": 0}
    orig_put = queue.put

    async def _put_once_then_ok(context):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Queue is full")
        return await orig_put(context)

    monkeypatch.setattr(queue, "put", _put_once_then_ok)
    monkeypatch.setattr("Message._queue_put_retries", lambda: 3)
    monkeypatch.setattr("Message._queue_put_retry_delay_sec", lambda: 0.01)

    # 先腾出空间
    await queue.get(timeout=0.1)
    msg_id = await put_message(queue_name, ctx)
    assert msg_id
    assert calls["n"] >= 1

    queue_manager._queues.pop(queue_name, None)


@pytest.mark.asyncio
async def test_customer_agent_arun_serializes_on_same_loop():
    from Agent.CustomerAgent.agent import CustomerAgent

    agent = CustomerAgent(knowledge_manager=MagicMock())
    agent._agent = MagicMock()
    order: list[str] = []

    async def _slow_arun(**_kwargs):
        order.append("start")
        await asyncio.sleep(0.05)
        order.append("end")
        return MagicMock(content="ok")

    agent._agent.arun = _slow_arun
    agent._is_initialized = True

    ctx = Context(
        type=ContextType.TEXT,
        content="q",
        channel_type=ChannelType.PINDUODUO,
        kwargs=type(
            "K",
            (),
            {
                "shop_name": "s",
                "shop_id": "1",
                "user_id": "u",
                "from_uid": "b1",
            },
        )(),
    )

    with patch.object(agent, "_build_input_with_transcript", return_value="q"), patch(
        "Agent.CustomerAgent.agent.set_platform_shop_context", return_value=MagicMock()
    ), patch("Agent.CustomerAgent.agent.reset_platform_shop_context"):
        await asyncio.gather(
            agent.async_reply("q1", ctx),
            agent.async_reply("q2", ctx),
        )

    assert order.index("start") < order.index("end")
    # 两次 arun 串行：第二个 start 在第一个 end 之后
    assert order.count("start") == 2
    assert order[2] == "start"


def test_hub_civility_skips_memory_on_persist_failure():
    from ui.conversation_hub import ConversationHub
    from bridge.context import PinduoduoKwargs

    hub = ConversationHub()
    ctx = Context(
        type=ContextType.SYSTEM_HINT,
        content="请文明用语",
        channel_type=ChannelType.PINDUODUO,
        kwargs=PinduoduoKwargs(from_uid="b1", shop_id="s1", user_id="u1"),
    )
    with patch(
        "database.chat_persist.persist_platform_civility_from_context",
        side_effect=RuntimeError("db"),
    ), patch.object(hub, "_refresh_or_touch") as mock_touch:
        hub.record_platform_civility_from_context("pinduoduo", "s1", "u1", "cs", ctx)
    mock_touch.assert_not_called()


def test_hub_manual_sent_skips_memory_on_persist_failure():
    from ui.conversation_hub import ConversationHub

    hub = ConversationHub()
    with patch(
        "database.chat_persist.persist_human_message",
        side_effect=RuntimeError("db"),
    ), patch.object(hub, "notify_persisted_message") as mock_notify:
        hub.record_manual_sent("pinduoduo", "s1", "cs", "buyer1", "hi", "u1")
    mock_notify.assert_not_called()


def test_can_handle_uses_metadata_stage_cache():
    from Message.handlers.base import BaseHandler
    from bridge.context import Context, ContextType, ChannelType

    class _H(BaseHandler):
        allowed_stages = frozenset({"idle"})

        def _can_handle_impl(self, context: Context) -> bool:
            return True

        async def handle(self, context: Context, metadata: dict) -> bool:
            return False

    h = _H()
    ctx = Context(type=ContextType.TEXT, content="x", channel_type=ChannelType.PINDUODUO)
    meta = {"_session_stage": "after_sales"}
    with patch(
        "Agent.CustomerAgent.conversation_memory.get_current_stage",
        return_value="after_sales",
    ) as mock_stage:
        assert h.can_handle(ctx, meta) is False
        mock_stage.assert_called_once()
        assert mock_stage.call_args[0][1] is meta
