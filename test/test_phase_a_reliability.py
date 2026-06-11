"""Phase A 可靠性闭环 TDD：dead-letter drain、process 失败、watchdog、shutdown。"""
from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import ChannelType, Context, ContextType, PinduoduoKwargs
from database.schema_migrations import migrate_message_dead_letters_table
from Message.core.consumer import MessageConsumer, MessageConsumerManager
from Message.models.queue_models import MessageWrapper, QueueConfig
from sqlalchemy import create_engine


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        migrate_message_dead_letters_table(engine)

        def _cfg(key, default=None):
            if key == "db_path":
                return db_path
            if key == "chat.dead_letter_enabled":
                return True
            return default

        monkeypatch.setattr("config.get_config", _cfg)
        monkeypatch.setattr("Message.dead_letter.get_config", _cfg)
        yield db_path


def _ctx(content: str = "买家消息", msg_id: str = "m-pa-1") -> Context:
    return Context(
        type=ContextType.TEXT,
        content=content,
        channel_type=ChannelType.PINDUODUO,
        kwargs=PinduoduoKwargs(
            from_uid="buyer_pa",
            shop_id="shop1",
            user_id="seller1",
            msg_id=msg_id,
        ),
    )


def _wrapper(content: str = "买家消息", msg_id: str = "m-pa-1") -> MessageWrapper:
    return MessageWrapper(message_id=msg_id, context=_ctx(content, msg_id), timestamp=0.0)


def _dead_letter_count(temp_db: str, reason: str | None = None) -> int:
    conn = sqlite3.connect(temp_db)
    try:
        if reason:
            row = conn.execute(
                "SELECT COUNT(*) FROM message_dead_letters WHERE reason = ?",
                (reason,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM message_dead_letters").fetchone()
        return int(row[0])
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_process_failure_persists_dead_letter(temp_db, monkeypatch):
    consumer = MessageConsumer("pa_fail_q", max_concurrent=1)
    consumer.handlers = []

    with patch(
        "database.session_store.prime_metadata_session"
    ), patch(
        "Agent.CustomerAgent.conversation_memory.prime_session_stage_on_context"
    ), patch("utils.intent_stage_reset.try_intent_stage_reset", return_value=False), patch(
        "utils.inbound_transfer_gate.should_block_handler_until_transfer",
        return_value=False,
    ), patch(
        "Message.handlers.ai_reply_watchdog.start_inbound_watchdog",
        new_callable=AsyncMock,
        return_value=0,
    ), patch(
        "Message.handlers.fallback_reply.try_send_unhandled_fallback",
        new_callable=AsyncMock,
        return_value=False,
    ), patch("Message.dead_letter._db_path", return_value=temp_db):
        await consumer._process_message(_wrapper())

    assert _dead_letter_count(temp_db, "process_failure") == 1


@pytest.mark.asyncio
async def test_queue_drain_to_dead_letter(temp_db, monkeypatch):
    from Message.core.queue import SimpleMessageQueue

    monkeypatch.setattr("Message.core.queue.get_config", lambda k, d=None: True if k == "chat.dead_letter_enabled" else d)

    q = SimpleMessageQueue("drain_q", QueueConfig(max_size=10, enable_deduplication=False))
    await q.put(_ctx("第一条"))
    await q.put(_ctx("第二条", msg_id="m-pa-2"))

    with patch("Message.dead_letter._db_path", return_value=temp_db):
        drained = q.drain_to_dead_letter("queue_drain")

    assert drained == 2
    assert q.is_empty()
    assert _dead_letter_count(temp_db, "queue_drain") == 2


def test_recreate_queue_drains_old_messages(temp_db, monkeypatch):
    from Message.core.queue import queue_manager

    def _cfg(key, default=None):
        if key == "db_path":
            return temp_db
        if key == "chat.dead_letter_enabled":
            return True
        return default

    monkeypatch.setattr("config.get_config", _cfg)
    monkeypatch.setattr("Message.core.queue.get_config", _cfg)

    queue_name = "pa_recreate_q"
    queue_manager._queues.pop(queue_name, None)
    old = queue_manager.get_or_create_queue(
        queue_name, QueueConfig(max_size=10, enable_deduplication=False)
    )

    async def _enqueue():
        await old.put(_ctx("待 drain"))

    asyncio.run(_enqueue())

    with patch("Message.dead_letter._db_path", return_value=temp_db):
        queue_manager.recreate_queue(queue_name)

    assert _dead_letter_count(temp_db, "queue_recreate") >= 1
    new_q = queue_manager.get_queue(queue_name)
    assert new_q is not None
    assert new_q.is_empty()
    queue_manager._queues.pop(queue_name, None)


@pytest.mark.asyncio
async def test_consumer_stop_drains_queued_messages(temp_db, monkeypatch):
    from Message.core.queue import queue_manager

    queue_name = "pa_stop_drain_q"
    queue_manager._queues.pop(queue_name, None)
    queue = queue_manager.get_or_create_queue(
        queue_name, QueueConfig(max_size=10, enable_deduplication=False)
    )
    await queue.put(_ctx("排队中"))

    consumer = MessageConsumer(queue_name, max_concurrent=1)
    consumer.handlers = []

    class _SlowHandler:
        started = asyncio.Event()
        release = asyncio.Event()

        def can_handle(self, _ctx, _meta):
            return True

        async def handle(self, _ctx, _meta):
            self.started.set()
            await self.release.wait()
            return True

    slow = _SlowHandler()
    consumer.add_handler(slow)

    await consumer.start()
    await queue.put(_ctx("在途", msg_id="m-inflight"))
    await asyncio.wait_for(slow.started.wait(), timeout=2.0)

    with patch("Message.dead_letter._db_path", return_value=temp_db):
        slow.release.set()
        await consumer.stop()

    assert _dead_letter_count(temp_db, "consumer_stop") >= 1
    queue_manager._queues.pop(queue_name, None)


@pytest.mark.asyncio
async def test_replay_marks_skipped_dedup_not_pending(temp_db, monkeypatch):
    from Message.dead_letter import persist_dead_letter, replay_pending_for_queue
    from Message.core.queue import queue_manager

    queue_name = "pa_dedup_q"
    queue_manager._queues.pop(queue_name, None)
    queue_manager.get_or_create_queue(
        queue_name, QueueConfig(max_size=10, enable_deduplication=False),
    )

    with patch("Message.dead_letter._db_path", return_value=temp_db):
        letter_id = persist_dead_letter(queue_name, _ctx(), reason="test")
        assert letter_id is not None

        mock_queue = MagicMock()
        mock_queue.put = AsyncMock(return_value="")

        with patch(
            "Message.core.queue.queue_manager.get_or_create_queue",
            return_value=mock_queue,
        ):
            replayed = await replay_pending_for_queue(queue_name)

    assert replayed == 0
    conn = sqlite3.connect(temp_db)
    try:
        status = conn.execute(
            "SELECT status FROM message_dead_letters WHERE id = ?",
            (letter_id,),
        ).fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM message_dead_letters WHERE status = 'pending'",
        ).fetchone()[0]
    finally:
        conn.close()
    assert status == "skipped_dedup"
    assert pending == 0
    queue_manager._queues.pop(queue_name, None)


@pytest.mark.asyncio
async def test_logistics_handler_notifies_watchdog(temp_db):
    from Message.handlers.order_logistics_handler import OrderLogisticsHandler

    handler = OrderLogisticsHandler()
    ctx = _ctx("查物流 123456-123456789012345")
    metadata = {
        "shop_id": "shop1",
        "user_id": "seller1",
        "from_uid": "buyer_pa",
    }

    sender = MagicMock()
    sender.send_text.return_value = {"success": True}

    with patch(
        "Channel.pinduoduo.utils.API.logistics.lookup_order_logistics_reply",
        return_value=("您的包裹运输中", "123456-123456789012345", False),
    ), patch(
        "Channel.pinduoduo.utils.API.send_message.SendMessage",
        return_value=sender,
    ), patch(
        "Message.handlers.ai_reply_watchdog.notify_outbound_reply"
    ) as notify_mock:
        ok = await handler.handle(ctx, metadata)

    assert ok is True
    sender.send_text.assert_called_once()
    notify_mock.assert_called_once()


@pytest.mark.asyncio
async def test_transfer_success_notifies_watchdog():
    from Message.handlers.channel_send import transfer_to_available_cs_async

    metadata = {"shop_id": "s", "user_id": "u", "from_uid": "b"}
    ctx = _ctx()

    with patch(
        "Message.handlers.channel_send.get_cs_list_async",
        new_callable=AsyncMock,
        return_value={"csList": [{"id": "cs1", "load": 0}]},
    ), patch(
        "Message.handlers.channel_send.move_conversation_async",
        new_callable=AsyncMock,
        return_value={"success": True},
    ), patch(
        "utils.pdd_transfer.pick_transfer_cs_uid",
        return_value="cs1",
    ), patch(
        "Message.handlers.ai_reply_watchdog.notify_outbound_reply"
    ) as notify_mock:
        ok = await transfer_to_available_cs_async(
            "s", "u", "b", context=ctx, metadata=metadata
        )

    assert ok is True
    notify_mock.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_task_set_waits_for_completion_before_cancel():
    from Channel.pinduoduo.ws_task_cleanup import cancel_task_set

    tasks: set[asyncio.Task] = set()
    done_flag = {"v": False}

    async def _work():
        await asyncio.sleep(0.05)
        done_flag["v"] = True

    tasks.add(asyncio.create_task(_work()))
    await cancel_task_set(tasks, drain_wait_sec=1.0)
    assert done_flag["v"] is True
    assert len(tasks) == 0


def test_shutdown_calls_stop_all_when_consumers_still_running(monkeypatch):
    from core import app_shutdown

    app_shutdown._done = False
    calls = {"stop_all_cross_loop": 0, "detach": 0}

    class _RunningConsumer:
        def is_running(self):
            return True

    class _FakeConsumerMgr:
        def list_consumers(self):
            return ["pdd_s_u"]

        def get_consumer(self, _name):
            return _RunningConsumer()

        def stop_all_cross_loop(self, timeout=6.0):
            calls["stop_all_cross_loop"] += 1

        def detach_all(self):
            calls["detach"] += 1

    monkeypatch.setattr(
        "Message.core.consumer.message_consumer_manager",
        _FakeConsumerMgr(),
    )
    monkeypatch.setattr(
        "ui.auto_reply_ui.auto_reply_manager.stop_all",
        lambda: None,
    )
    monkeypatch.setattr(
        "core.pdd_channel_registry.iter_registered_channels",
        lambda: [],
    )

    async def _cancel_wd():
        return None

    monkeypatch.setattr(
        "Message.handlers.ai_reply_watchdog.cancel_all_watchdogs",
        _cancel_wd,
    )
    monkeypatch.setattr(
        "core.production_services.stop_production_background_services",
        lambda: None,
    )

    asyncio.run(app_shutdown.stop_all_services())
    assert calls["stop_all_cross_loop"] == 1
    assert calls["detach"] == 1
