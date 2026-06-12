"""出站 Outbox：pending → sent / 重试不重生成。"""
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from database.outbound_outbox import (
    claim_for_send,
    create_pending,
    fetch_due_retries,
    mark_failed,
    mark_sent,
    session_has_active_outbox,
)
from utils.outbound_outbox_retry import retry_outbox_row_sync


@pytest.fixture
def outbox_db(tmp_path, monkeypatch):
    db_file = tmp_path / "outbox_test.db"
    monkeypatch.setenv("CUSTOMER_AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "database.outbound_outbox._db_path",
        lambda: str(db_file),
    )
    monkeypatch.setattr(
        "utils.outbound_outbox_retry._db_path",
        lambda: str(db_file),
        raising=False,
    )
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE outbound_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            account_id INTEGER NOT NULL,
            channel_name TEXT NOT NULL DEFAULT 'pinduoduo',
            shop_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            buyer_uid TEXT NOT NULL,
            login_username TEXT,
            content TEXT NOT NULL,
            message_kind TEXT NOT NULL DEFAULT 'text',
            payload_json TEXT,
            sender_type TEXT NOT NULL DEFAULT 'ai',
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            last_attempt_at REAL,
            error_detail TEXT,
            chat_message_id INTEGER,
            created_at REAL NOT NULL,
            sent_at REAL
        )
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr("database.outbound_outbox.outbox_enabled", lambda: True)
    return db_file


def test_create_pending_with_card_kind(outbox_db):
    from database.outbound_outbox import get_row

    oid = create_pending(
        session_id=10,
        account_id=10,
        channel_name="pinduoduo",
        shop_id="s1",
        user_id="u1",
        buyer_uid="b10",
        content="[goods_card] goods_id=1",
        message_kind="goods_card",
        payload={"goods_id": 1, "biz_type": 2},
    )
    assert oid is not None
    row = get_row(int(oid))
    assert row is not None
    assert row.get("message_kind") == "goods_card"
    assert "goods_id" in str(row.get("payload_json") or "")


def test_create_pending_and_mark_sent(outbox_db):
    oid = create_pending(
        session_id=1,
        account_id=10,
        channel_name="pinduoduo",
        shop_id="s1",
        user_id="u1",
        buyer_uid="b1",
        content="测试回复",
    )
    assert oid is not None
    assert session_has_active_outbox(1) is True
    claim_for_send(int(oid))
    mark_sent(int(oid), chat_message_id=99)
    assert session_has_active_outbox(1) is False


def test_retry_uses_receipt_without_resend(outbox_db, monkeypatch):
    oid = create_pending(
        session_id=2,
        account_id=10,
        channel_name="pinduoduo",
        shop_id="s1",
        user_id="u1",
        buyer_uid="b2",
        content="同一句",
    )
    from database.outbound_outbox import get_row

    row = get_row(int(oid))
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


def test_mark_failed_dead_emits_alert(outbox_db, monkeypatch):
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
        content="dead alert",
    )
    for _ in range(3):
        claim_for_send(int(oid))
        final = mark_failed(int(oid), "boom")
    assert final == "dead"
    assert len(emitted) == 1
    assert int(emitted[0]["id"]) == int(oid)


def test_mark_failed_dead_after_max_attempts(outbox_db):
    oid = create_pending(
        session_id=3,
        account_id=10,
        channel_name="pinduoduo",
        shop_id="s1",
        user_id="u1",
        buyer_uid="b3",
        content="fail",
    )
    for _ in range(3):
        claim_for_send(int(oid))
        final = mark_failed(int(oid), "err")
    assert final == "dead"
    rows = fetch_due_retries(account_id=10, limit=5)
    assert not any(int(r["id"]) == int(oid) for r in rows)
