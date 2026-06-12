"""出站 Outbox：RETURNING 认领、retry_count、去重、processing 回收。"""
from __future__ import annotations

import sqlite3
import time
from unittest.mock import MagicMock, patch

import pytest

from database.outbound_outbox import (
    claim_by_id,
    claim_due_outbox,
    claim_for_send,
    create_pending,
    get_row,
    mark_failed,
    mark_sent,
    reset_stale_processing,
    session_has_active_outbox,
)
from utils.outbound_outbox_retry import retry_outbox_row_sync

_OUTBOX_DDL = """
CREATE TABLE outbound_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    channel_name TEXT NOT NULL DEFAULT 'pinduoduo',
    shop_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    buyer_uid TEXT NOT NULL,
    buyer_msg_id TEXT NOT NULL DEFAULT '',
    login_username TEXT,
    content TEXT NOT NULL,
    message_kind TEXT NOT NULL DEFAULT 'text',
    payload_json TEXT,
    sender_type TEXT NOT NULL DEFAULT 'ai',
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    retry_count INTEGER NOT NULL DEFAULT 0,
    processing_at REAL,
    last_attempt_at REAL,
    error_detail TEXT,
    chat_message_id INTEGER,
    created_at REAL NOT NULL,
    sent_at REAL
);
CREATE UNIQUE INDEX uq_outbox_session_buyer_msg_channel
ON outbound_outbox (session_id, buyer_msg_id, channel_name);
"""


@pytest.fixture
def outbox_db(tmp_path, monkeypatch):
    db_file = tmp_path / "outbox_test.db"
    monkeypatch.setenv("CUSTOMER_AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "database.outbound_outbox._db_path",
        lambda: str(db_file),
    )
    conn = sqlite3.connect(str(db_file))
    conn.executescript(_OUTBOX_DDL)
    conn.commit()
    conn.close()
    monkeypatch.setattr("database.outbound_outbox.outbox_enabled", lambda: True)
    return db_file


def test_create_pending_dedup_same_buyer_msg_id(outbox_db):
    a = create_pending(
        session_id=10,
        account_id=10,
        channel_name="pinduoduo",
        shop_id="s1",
        user_id="u1",
        buyer_uid="b10",
        buyer_msg_id="msg-100",
        content="reply-1",
    )
    b = create_pending(
        session_id=10,
        account_id=10,
        channel_name="pinduoduo",
        shop_id="s1",
        user_id="u1",
        buyer_uid="b10",
        buyer_msg_id="msg-100",
        content="reply-dup",
    )
    assert a is not None
    assert b == a


def test_create_pending_with_card_kind(outbox_db):
    oid = create_pending(
        session_id=10,
        account_id=10,
        channel_name="pinduoduo",
        shop_id="s1",
        user_id="u1",
        buyer_uid="b10",
        buyer_msg_id="card-1",
        content="[goods_card] goods_id=1",
        message_kind="goods_card",
        payload={"goods_id": 1, "biz_type": 2},
    )
    assert oid is not None
    row = get_row(int(oid))
    assert row is not None
    assert row.get("message_kind") == "goods_card"
    assert "goods_id" in str(row.get("payload_json") or "")


def test_claim_by_id_returning_and_mark_sent(outbox_db):
    oid = create_pending(
        session_id=1,
        account_id=10,
        channel_name="pinduoduo",
        shop_id="s1",
        user_id="u1",
        buyer_uid="b1",
        buyer_msg_id="m1",
        content="测试回复",
    )
    assert oid is not None
    assert session_has_active_outbox(1) is True
    row = claim_by_id(int(oid))
    assert row is not None
    assert row.get("status") == "processing"
    assert claim_for_send(int(oid)) is False
    mark_sent(int(oid), chat_message_id=99)
    assert session_has_active_outbox(1) is False


def test_claim_due_outbox_atomic(outbox_db, monkeypatch):
    monkeypatch.setattr("database.outbound_outbox._retry_interval_sec", lambda: 0.0)
    oid = create_pending(
        session_id=5,
        account_id=10,
        channel_name="pinduoduo",
        shop_id="s1",
        user_id="u1",
        buyer_uid="b5",
        buyer_msg_id="due-1",
        content="due",
    )
    rows = claim_due_outbox(account_id=10, limit=5)
    assert len(rows) == 1
    assert int(rows[0]["id"]) == int(oid)
    assert rows[0]["status"] == "processing"


def test_retry_uses_receipt_without_resend(outbox_db, monkeypatch):
    oid = create_pending(
        session_id=2,
        account_id=10,
        channel_name="pinduoduo",
        shop_id="s1",
        user_id="u1",
        buyer_uid="b2",
        buyer_msg_id="m2",
        content="同一句",
    )
    row = claim_by_id(int(oid))
    assert row is not None
    send_mock = MagicMock()
    monkeypatch.setattr(
        "utils.outbound_receipt.has_recent_outbound_receipt",
        lambda key, within_sec=21600.0: True,
    )
    with patch(
        "Channel.pinduoduo.utils.API.send_message.SendMessage",
        return_value=send_mock,
    ), patch(
        "utils.outbound_outbox_retry._persist_outbox_content",
        return_value=2,
    ):
        ok = retry_outbox_row_sync(row)
    assert ok is True
    send_mock.send_text.assert_not_called()


def test_mark_failed_increments_retry_count_to_dead(outbox_db, monkeypatch):
    emitted = []
    monkeypatch.setattr(
        "core.human_assist_bus.emit_outbox_dead_alert",
        lambda row: emitted.append(dict(row)),
    )
    oid = create_pending(
        session_id=4,
        account_id=10,
        channel_name="pinduoduo",
        shop_id="s1",
        user_id="u1",
        buyer_uid="b4",
        buyer_msg_id="dead-1",
        content="dead alert",
    )
    for _ in range(3):
        assert claim_by_id(int(oid)) is not None
        final = mark_failed(int(oid), "boom")
    assert final == "dead"
    assert len(emitted) == 1
    row = get_row(int(oid))
    assert row is not None
    assert int(row.get("retry_count") or 0) >= 3


def test_reset_stale_processing_reclaims(outbox_db, monkeypatch):
    oid = create_pending(
        session_id=3,
        account_id=10,
        channel_name="pinduoduo",
        shop_id="s1",
        user_id="u1",
        buyer_uid="b3",
        buyer_msg_id="stale-1",
        content="stale",
    )
    row = claim_by_id(int(oid))
    assert row is not None
    conn = sqlite3.connect(str(outbox_db))
    conn.execute(
        "UPDATE outbound_outbox SET processing_at = ? WHERE id = ?",
        (time.time() - 600, int(oid)),
    )
    conn.commit()
    conn.close()
    n = reset_stale_processing(max_age_sec=300.0)
    assert n >= 1
    row = get_row(int(oid))
    assert row is not None
    assert row.get("status") == "failed"
