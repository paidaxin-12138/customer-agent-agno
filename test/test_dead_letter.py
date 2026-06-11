"""dead-letter 持久化与重放测试。"""
from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import ChannelType, Context, ContextType, PinduoduoKwargs
from core.turn_abort import TurnAborted
from database.schema_migrations import migrate_message_dead_letters_table
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
        yield db_path


def _ctx() -> Context:
    return Context(
        type=ContextType.TEXT,
        content="买家问价",
        channel_type=ChannelType.PINDUODUO,
        kwargs=PinduoduoKwargs(
            from_uid="buyer_dl",
            shop_id="shop1",
            user_id="seller1",
            msg_id="m-dl-1",
        ),
    )


def test_persist_dead_letter_writes_sqlite(temp_db):
    from Message.dead_letter import persist_dead_letter

    letter_id = persist_dead_letter("pdd_shop1_seller1", _ctx())
    assert letter_id is not None
    conn = sqlite3.connect(temp_db)
    try:
        row = conn.execute(
            "SELECT status, from_uid, queue_name FROM message_dead_letters WHERE id = ?",
            (letter_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "pending"
    assert row[1] == "buyer_dl"
    assert row[2] == "pdd_shop1_seller1"


@pytest.mark.asyncio
async def test_put_message_returns_dead_letter_id_when_exhausted(temp_db, monkeypatch):
    from Message import put_message
    from Message.core.queue import queue_manager
    from Message.models.queue_models import QueueConfig

    queue_name = "dl_put_test_q"
    queue_manager._queues.pop(queue_name, None)
    queue = queue_manager.get_or_create_queue(
        queue_name,
        QueueConfig(max_size=1, enable_deduplication=False),
    )
    ctx = _ctx()
    await queue.put(ctx)
    assert queue.size() == 1

    monkeypatch.setattr("Message._queue_put_retries", lambda: 2)
    monkeypatch.setattr("Message._queue_put_retry_delay_sec", lambda: 0.01)

    with patch("Message.dead_letter._db_path", return_value=temp_db):
        wrapper_id = await put_message(queue_name, ctx)

    assert str(wrapper_id).startswith("dead-letter:")
    queue_manager._queues.pop(queue_name, None)


@pytest.mark.asyncio
async def test_replay_pending_for_queue(temp_db, monkeypatch):
    from Message.dead_letter import persist_dead_letter, replay_pending_for_queue
    from Message.core.queue import queue_manager
    from Message.models.queue_models import QueueConfig

    queue_name = "dl_replay_q"
    queue_manager._queues.pop(queue_name, None)
    queue_manager.get_or_create_queue(
        queue_name,
        QueueConfig(max_size=10, enable_deduplication=False),
    )

    with patch("Message.dead_letter._db_path", return_value=temp_db):
        letter_id = persist_dead_letter(queue_name, _ctx())
        assert letter_id is not None
        replayed = await replay_pending_for_queue(queue_name)

    assert replayed == 1
    conn = sqlite3.connect(temp_db)
    try:
        status = conn.execute(
            "SELECT status FROM message_dead_letters WHERE id = ?",
            (letter_id,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert status == "replayed"
    queue_manager._queues.pop(queue_name, None)


@pytest.mark.asyncio
async def test_agent_arun_timeout_raises():
    from Agent.CustomerAgent.agent import CustomerAgent

    agent = CustomerAgent(knowledge_manager=MagicMock())
    agent._agent = MagicMock()
    agent._is_initialized = True

    def _slow_blocking(*_a, **_k):
        import time

        time.sleep(5.0)
        return MagicMock(content="late")

    agent._run_agent_arun_blocking = _slow_blocking

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

    with patch.object(agent, "_build_input_with_transcript", return_value="q"), patch(
        "Agent.CustomerAgent.agent._llm_arun_timeout_sec", return_value=0.05
    ), patch(
        "Agent.CustomerAgent.agent.set_platform_shop_context", return_value=MagicMock()
    ), patch("Agent.CustomerAgent.agent.reset_platform_shop_context"):
        with pytest.raises(TurnAborted) as exc:
            await agent.async_reply("q", ctx)
    assert exc.value.reason == "arun_timeout"


def test_purge_old_dead_letters(temp_db):
    from Message.dead_letter import persist_dead_letter, purge_old_dead_letters
    import sqlite3
    import time as _time

    letter_id = persist_dead_letter("q1", _ctx(), reason="test")
    assert letter_id is not None
    conn = sqlite3.connect(temp_db)
    try:
        conn.execute(
            "UPDATE message_dead_letters SET status = ?, created_at = ? WHERE id = ?",
            ("replayed", _time.time() - 20 * 86400, letter_id),
        )
        conn.commit()
    finally:
        conn.close()
    removed = purge_old_dead_letters(retention_days=14)
    assert removed == 1


@pytest.mark.asyncio
async def test_force_enqueue_writes_dead_letter_for_dropped(temp_db, monkeypatch):
    from Message.core.queue import SimpleMessageQueue
    from Message.models.queue_models import QueueConfig, MessageWrapper
    import sqlite3

    def _cfg(key, default=None):
        if key == "db_path":
            return temp_db
        if key == "chat.dead_letter_enabled":
            return True
        if key == "chat.queue_force_enqueue":
            return True
        return default

    monkeypatch.setattr("config.get_config", _cfg)
    monkeypatch.setattr("Message.core.queue.get_config", _cfg)

    q = SimpleMessageQueue("force_q", QueueConfig(max_size=1, enable_deduplication=False))
    ctx1 = _ctx()
    ctx2 = Context(
        type=ContextType.TEXT,
        content="第二条",
        channel_type=ChannelType.PINDUODUO,
        kwargs=PinduoduoKwargs(from_uid="buyer2", shop_id="s", user_id="u"),
    )
    await q.put(ctx1)
    await q.put(ctx2)

    conn = sqlite3.connect(temp_db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM message_dead_letters WHERE reason = ?",
            ("force_enqueue_drop",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert int(count) >= 1


@pytest.mark.asyncio
async def test_consumer_idle_replays_dead_letters(temp_db, monkeypatch):
    from Message.core.consumer import MessageConsumer

    def _cfg(key, default=None):
        if key == "db_path":
            return temp_db
        if key == "chat.dead_letter_enabled":
            return True
        if key == "chat.dead_letter_periodic_replay_enabled":
            return True
        if key == "chat.dead_letter_replay_interval_sec":
            return 0
        return default

    monkeypatch.setattr("config.get_config", _cfg)

    consumer = MessageConsumer("idle_dl_q", max_concurrent=1)
    consumer._last_dead_letter_replay = 0.0

    async def _replay_two(_q: str) -> int:
        return 2

    with patch(
        "Message.dead_letter.replay_pending_for_queue",
        side_effect=_replay_two,
    ) as mock_replay:
        await consumer._maybe_replay_dead_letters(0)
        mock_replay.assert_called_once_with("idle_dl_q")

    async def _replay_zero(_q: str) -> int:
        return 0

    with patch(
        "Message.dead_letter.replay_pending_for_queue",
        side_effect=_replay_zero,
    ) as mock_replay:
        await consumer._maybe_replay_dead_letters(1)
        mock_replay.assert_not_called()
