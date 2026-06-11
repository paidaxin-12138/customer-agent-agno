"""P1 诊断项 TDD 修复。"""
from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import ChannelType, Context, ContextType
from core.connection_status import ConnectionStatusManager


def _ctx(text: str = "我要退货") -> Context:
    return Context(type=ContextType.TEXT, content=text, channel_type=ChannelType.PINDUODUO)


@pytest.mark.asyncio
async def test_cleanup_processing_tasks_passes_payloads_and_queue_names():
    from Channel.pinduoduo.pdd_channel import PDDChannel

    channel = PDDChannel(
        max_concurrent_messages=4, status_manager=ConnectionStatusManager()
    )
    channel.processing_task_payloads["dummy"] = '{"frame":1}'  # type: ignore[index]
    channel.processing_task_queue_names["dummy"] = "pdd_shop_user"  # type: ignore[index]

    with patch(
        "Channel.pinduoduo.pdd_channel.cancel_task_set",
        new_callable=AsyncMock,
    ) as mock_cancel:
        await channel.cleanup_processing_tasks()

    mock_cancel.assert_awaited_once()
    kwargs = mock_cancel.await_args.kwargs
    assert kwargs["task_payloads"] is channel.processing_task_payloads
    assert kwargs["task_queue_names"] is channel.processing_task_queue_names


@pytest.mark.asyncio
async def test_close_websocket_persists_cancelled_ws_frame():
    from Channel.pinduoduo.pdd_channel import PDDChannel

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "t.db")
        from database.schema_migrations import migrate_message_dead_letters_table
        from sqlalchemy import create_engine

        migrate_message_dead_letters_table(create_engine(f"sqlite:///{db_path}"))

        channel = PDDChannel(
            max_concurrent_messages=4, status_manager=ConnectionStatusManager()
        )
        blocker = asyncio.Event()
        payloads = channel.processing_task_payloads
        qnames = channel.processing_task_queue_names

        async def _slow():
            await blocker.wait()

        t = asyncio.create_task(_slow())
        channel.processing_tasks.add(t)
        payloads[t] = '{"type":"close_test"}'
        qnames[t] = "pdd_s_u"

        with patch.object(channel, "stop_all_connections", new_callable=AsyncMock), patch(
            "Message.dead_letter._db_path", return_value=db_path
        ):
            await channel.close_websocket()

        conn = sqlite3.connect(db_path)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM message_dead_letters WHERE queue_name = ?",
                ("pdd_s_u",),
            ).fetchone()[0]
        finally:
            conn.close()
        assert count >= 1


@pytest.mark.asyncio
async def test_after_sales_transfer_notifies_watchdog():
    from Message.handlers.after_sales_apply_handler import AfterSalesApplyHandler

    handler = AfterSalesApplyHandler()
    ctx = _ctx()
    metadata = {"shop_id": "s", "user_id": "u", "from_uid": "b"}

    with patch.object(handler, "_send_text", new_callable=AsyncMock), patch(
        "Message.handlers.channel_send.transfer_to_available_cs_async",
        new_callable=AsyncMock,
        return_value=True,
    ) as transfer_mock, patch(
        "core.human_assist_bus.emit_human_assist"
    ):
        await handler._transfer_to_human(ctx, metadata, "s", "u", "b", "请稍等")

    transfer_mock.assert_awaited_once()
    _, kwargs = transfer_mock.call_args
    assert kwargs.get("context") is ctx
    assert kwargs.get("metadata") is metadata


@pytest.mark.asyncio
async def test_after_sales_send_text_passes_context_to_watchdog():
    from Message.handlers.after_sales_apply_handler import AfterSalesApplyHandler

    handler = AfterSalesApplyHandler()
    ctx = _ctx()
    metadata = {"shop_id": "s", "user_id": "u", "from_uid": "b"}

    with patch.object(
        handler,
        "send_text_to_buyer",
        new_callable=AsyncMock,
        return_value=True,
    ) as send_mock:
        await handler._send_text("s", "u", "b", "话术", metadata=metadata, context=ctx)

    send_mock.assert_awaited_once()
    _, kwargs = send_mock.call_args
    assert kwargs.get("context") is ctx
    assert kwargs.get("metadata") is metadata


def test_update_document_under_io_lock(tmp_path):
    from Agent.CustomerAgent.knowledge_indexer import KnowledgeIndexerMixin
    from Agent.CustomerAgent.knowledge_storage import KnowledgeStorageMixin

    class _Probe(KnowledgeIndexerMixin, KnowledgeStorageMixin):
        pass

    probe = _Probe()
    probe._store_file = tmp_path / "docs.json"
    probe.documents = [{"id": "d1", "content": "old", "title": "t"}]
    probe._add_doc_to_lancedb = MagicMock(return_value=True)
    probe._lancedb_delete_by_id = MagicMock()

    lock_calls = []

    real_lock = probe._global_io_lock

    class _TrackingLock:
        def __enter__(self):
            lock_calls.append("enter")
            return real_lock.__enter__()

        def __exit__(self, *args):
            return real_lock.__exit__(*args)

    probe._global_io_lock = _TrackingLock()

    ok = probe.update_document("d1", {"content": "new"})
    assert ok is True
    assert lock_calls, "update_document 应在 _global_io_lock 内执行"
    assert probe.documents[0]["content"] == "new"


def test_stop_all_cross_loop_stops_on_owner_loop():
    from Message.core.consumer import MessageConsumer, MessageConsumerManager

    ready = threading.Event()
    holder: dict = {}

    def _worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        consumer = MessageConsumer("pdd_cross_test", max_concurrent=1)

        async def _setup():
            consumer._owner_loop = asyncio.get_running_loop()
            consumer.running = True
            consumer.consumer_task = asyncio.create_task(asyncio.sleep(3600))
            holder["consumer"] = consumer
            holder["loop"] = asyncio.get_running_loop()
            ready.set()
            await asyncio.sleep(3600)

        try:
            loop.run_until_complete(_setup())
        except asyncio.CancelledError:
            pass

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    assert ready.wait(5)

    mgr = MessageConsumerManager()
    mgr._consumers["pdd_cross_test"] = holder["consumer"]

    with patch.object(MessageConsumer, "stop", new_callable=AsyncMock) as stop_mock:
        mgr.stop_all_cross_loop(timeout=3.0)
        stop_mock.assert_awaited_once()

    assert "pdd_cross_test" not in mgr._consumers
