"""chat_messages 批量写入缓冲测试。"""
import os

import pytest

from database.chat_message_buffer import FLUSH_BATCH_SIZE, ChatMessageWriteBuffer


@pytest.fixture(autouse=True)
def disable_buffer_env(monkeypatch):
    monkeypatch.delenv("CHAT_MESSAGE_BUFFER_DISABLE", raising=False)


def test_buffer_flushes_at_batch_size(monkeypatch):
    calls = []

    class FakeDb:
        def add_chat_messages_batch(self, batch):
            calls.append(list(batch))
            return len(batch)

    buf = ChatMessageWriteBuffer()
    buf._db = FakeDb()

    for i in range(FLUSH_BATCH_SIZE):
        buf.enqueue(
            session_id=1,
            account_id=2,
            sender_type="customer",
            content=f"m{i}",
        )
    assert len(calls) == 1
    assert len(calls[0]) == FLUSH_BATCH_SIZE


def test_flush_on_shutdown_helper(monkeypatch):
    flushed = []

    class FakeDb:
        def add_chat_messages_batch(self, batch):
            flushed.append(len(batch))
            return len(batch)

    buf = ChatMessageWriteBuffer()
    buf._db = FakeDb()
    buf.enqueue(session_id=1, account_id=1, sender_type="ai", content="hi")
    assert buf.flush() == 1
    assert flushed == [1]


def test_buffer_disabled_by_env(monkeypatch):
    monkeypatch.setenv("CHAT_MESSAGE_BUFFER_DISABLE", "1")
    from database.chat_message_buffer import _buffer_enabled

    assert _buffer_enabled() is False
