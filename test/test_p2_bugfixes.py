"""P2 / 剩余诊断项 TDD 修复。"""
from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import ChannelType, Context, ContextType, PinduoduoKwargs
from Message.core.consumer import MessageConsumer
from Message.core.handlers import MessageHandler
from Message.models.queue_models import MessageWrapper


class _SilentBusinessHandler(MessageHandler):
    """模拟业务 Handler：标记已处理但不发买家消息。"""

    async def handle(self, context: Context, metadata: Dict[str, Any]) -> bool:
        return True

    def can_handle(self, context: Context, metadata: Dict[str, Any] = None) -> bool:
        return True


def _make_wrapper(text: str = "改地址") -> MessageWrapper:
    kwargs = type(
        "Kwargs",
        (),
        {
            "from_uid": "b1",
            "shop_id": "s1",
            "user_id": "u1",
            "username": "cs",
        },
    )()
    ctx = Context(
        type=ContextType.TEXT,
        content=text,
        channel_type=ChannelType.PINDUODUO,
        kwargs=kwargs,
    )
    return MessageWrapper(message_id="m1", context=ctx, timestamp=0.0)


@pytest.mark.asyncio
async def test_consumer_dismisses_watchdog_when_handler_without_outbound():
    consumer = MessageConsumer("p2_watchdog_q", max_concurrent=1)
    consumer.handlers = [_SilentBusinessHandler()]

    with patch(
        "Message.handlers.ai_reply_watchdog.start_inbound_watchdog",
        new_callable=AsyncMock,
        return_value=3,
    ), patch(
        "database.session_store.prime_metadata_session",
        return_value=None,
    ), patch(
        "Agent.CustomerAgent.conversation_memory.prime_session_stage_on_context",
        return_value=None,
    ), patch(
        "utils.intent_stage_reset.try_intent_stage_reset",
        return_value=False,
    ), patch(
        "Message.handlers.channel_send.notify_outbound_from_metadata",
    ) as notify_mock, patch.object(
        consumer, "_record_process_failure", MagicMock()
    ):
        await consumer._process_message(_make_wrapper())

    notify_mock.assert_called_once()


def test_save_documents_removes_tmp_on_replace_failure(tmp_path):
    from Agent.CustomerAgent.knowledge_indexer import KnowledgeIndexerMixin
    from Agent.CustomerAgent.knowledge_storage import KnowledgeStorageMixin

    class _Probe(KnowledgeIndexerMixin, KnowledgeStorageMixin):
        pass

    probe = _Probe()
    probe._store_file = tmp_path / "docs.json"
    probe.documents = [{"id": "d1", "content": "x", "title": "t"}]
    probe.logger = MagicMock()

    with patch("os.replace", side_effect=OSError("disk full")):
        probe._save_documents()

    tmp_file = tmp_path / "docs.json.tmp"
    assert not tmp_file.exists()


def test_offload_tool_cancels_future_on_timeout():
    from utils import agno_tool_offload as mod

    started = threading.Event()

    @mod.offload_tool
    def _slow_tool() -> str:
        started.set()
        threading.Event().wait(30)
        return "late"

    with patch.object(mod, "_tool_timeout_sec", return_value=0.05):
        result = _slow_tool()

    assert started.is_set()
    assert "超时" in result


@pytest.mark.asyncio
async def test_arun_uses_dedicated_single_worker_executor():
    from Agent.CustomerAgent.agent import CustomerAgent
    from core.arun_executor import ARUN_EXECUTOR as _ARUN_EXECUTOR

    assert _ARUN_EXECUTOR._max_workers == 1

    agent = CustomerAgent(knowledge_manager=MagicMock())
    agent._agent = MagicMock()
    agent._is_initialized = True
    run_output = MagicMock()
    run_output.content = "ok"

    loop = asyncio.get_running_loop()

    def _fake_run_in_executor(executor, fn, *args):
        fut = loop.create_future()
        if executor is _ARUN_EXECUTOR:
            fut.set_result(fn(*args))
        else:
            try:
                fut.set_result(fn(*args))
            except Exception as exc:
                fut.set_exception(exc)
        return fut

    with patch.object(
        loop, "run_in_executor", side_effect=_fake_run_in_executor
    ) as ri_mock, patch.object(
        agent, "_run_agent_arun_blocking", return_value=run_output
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

    assert reply.content == "ok"
    ri_mock.assert_called()
    assert ri_mock.call_args.args[0] is _ARUN_EXECUTOR
    blocking_mock.assert_called_once()
