"""Phase B：dedup msg_id、Hub flush、UI debounce、Agno arun 线程卸载。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import ChannelType, Context, ContextType, PinduoduoKwargs
from Message.core.queue import SimpleMessageQueue
from Message.models.queue_models import QueueConfig


def _ctx(content: str = "在吗", msg_id: str = "m1") -> Context:
    return Context(
        type=ContextType.TEXT,
        content=content,
        channel_type=ChannelType.PINDUODUO,
        kwargs=PinduoduoKwargs(
            from_uid="buyer_b",
            shop_id="s1",
            user_id="u1",
            msg_id=msg_id,
        ),
    )


@pytest.mark.asyncio
async def test_dedup_by_msg_id_allows_same_content():
    q = SimpleMessageQueue(
        "dedup_msg_q", QueueConfig(max_size=10, enable_deduplication=True)
    )
    await q.put(_ctx("在吗", "msg-a"))
    await q.put(_ctx("在吗", "msg-b"))
    assert q.size() == 2


@pytest.mark.asyncio
async def test_dedup_by_msg_id_blocks_duplicate_id():
    q = SimpleMessageQueue(
        "dedup_msg_q2", QueueConfig(max_size=10, enable_deduplication=True)
    )
    first = await q.put(_ctx("第一条", "same-id"))
    second = await q.put(_ctx("第二条", "same-id"))
    assert first
    assert second == ""
    assert q.size() == 1


def test_record_from_context_flushes_buffer_before_hub_sync():
    from ui.conversation_hub import ConversationHub

    hub = ConversationHub()
    ctx = _ctx("你好")
    ctx.kwargs.from_user = "user"
    ctx.kwargs.to_user = "mall_cs"
    ctx.kwargs.nickname = "买家A"

    order: list[str] = []

    def _flush():
        order.append("flush")

    def _sync(*_a, **_k):
        order.append("sync")
        return True

    with patch(
        "database.chat_persist.persist_customer_from_context",
        return_value=1,
    ), patch(
        "database.chat_message_buffer.flush_chat_message_buffer",
        side_effect=_flush,
    ), patch.object(hub, "_sync_from_db", side_effect=_sync), patch.object(
        hub, "_emit_hub_updates"
    ):
        hub.record_from_context("pinduoduo", "s1", "u1", "shop", ctx)

    assert order == ["flush", "sync"]


def test_hub_list_changed_debounced(qapp, qtbot):
    from ui.chat_ui import ChatLiveWidget

    with patch.object(ChatLiveWidget, "_initial_load", MagicMock()):
        widget = ChatLiveWidget()
    qtbot.addWidget(widget)
    widget._sync.stop()
    widget._hub_refresh_timer.stop()
    widget.account_list.reload = MagicMock()
    widget._schedule_session_tree_refresh = MagicMock()

    with patch("ui.chat_ui.get_config", return_value=200):
        widget._on_hub_list_changed("acc1")
        widget._on_hub_list_changed("acc1")
        widget._on_hub_list_changed("acc2")

    assert widget.account_list.reload.call_count == 0
    assert widget._schedule_session_tree_refresh.call_count == 0
    qtbot.wait(350)
    assert widget.account_list.reload.call_count == 1
    assert widget._schedule_session_tree_refresh.call_count == 1
    widget._hub_refresh_timer.stop()


@pytest.mark.asyncio
async def test_async_reply_offloads_arun_to_thread():
    from Agent.CustomerAgent.agent import CustomerAgent
    from core.arun_executor import ARUN_EXECUTOR as _ARUN_EXECUTOR

    agent = CustomerAgent(knowledge_manager=MagicMock())
    agent._agent = MagicMock()
    agent._is_initialized = True

    run_output = MagicMock()
    run_output.content = "回复"

    loop = asyncio.get_running_loop()

    def _fake_run_in_executor(executor, fn, *args):
        fut = loop.create_future()
        try:
            fut.set_result(fn(*args))
        except Exception as exc:
            fut.set_exception(exc)
        return fut

    with patch.object(
        loop, "run_in_executor", side_effect=_fake_run_in_executor
    ) as ri_mock, patch.object(
        agent,
        "_run_agent_arun_blocking",
        return_value=run_output,
    ) as blocking_mock, patch.object(
        agent, "_build_input_with_transcript", return_value="q"
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
        reply = await agent.async_reply("q", ctx)

    assert reply.content == "回复"
    arun_calls = [c for c in ri_mock.call_args_list if c.args[0] is _ARUN_EXECUTOR]
    assert len(arun_calls) == 1
    blocking_mock.assert_called_once()


def test_offload_tool_runs_body_in_thread():
    from utils.agno_tool_offload import offload_tool

    ran_in_other_thread = {"main": None, "worker": None}

    @offload_tool
    def _sample(x: int) -> int:
        import threading

        ran_in_other_thread["worker"] = threading.current_thread().name
        return x + 1

    import threading

    ran_in_other_thread["main"] = threading.current_thread().name
    assert _sample(1) == 2
    assert ran_in_other_thread["worker"] != ran_in_other_thread["main"]
