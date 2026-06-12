# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""ChatStoreMixin 单元测试。"""

from __future__ import annotations

import pytest

import database.db_manager as dm_module
from database.db_manager import DatabaseManager


@pytest.fixture
def chat_db(tmp_path, monkeypatch):
    DatabaseManager._instance = None
    path = str(tmp_path / "chat_store_test.db")
    db = DatabaseManager(db_path=path)
    dm_module._db_instance = db
    db.add_shop("pinduoduo", "shop-001", "测试店", "")
    db.add_account("pinduoduo", "shop-001", "uid-001", "testuser", "pass")
    monkeypatch.setenv("CHAT_MESSAGE_BUFFER_DISABLE", "1")
    yield db
    dm_module._db_instance = None
    DatabaseManager._instance = None


def _account_id(chat_db: DatabaseManager) -> int:
    return chat_db.get_account("pinduoduo", "shop-001", "uid-001")["id"]


def test_truncate_session_preview():
    short = DatabaseManager._truncate_session_preview("hello")
    assert short == "hello"
    long_text = "a" * 60
    out = DatabaseManager._truncate_session_preview(long_text, max_len=50)
    assert len(out) == 50
    assert out.endswith("…")


def test_count_unread_buyer_messages(chat_db):
    acc_id = _account_id(chat_db)
    sid = chat_db.get_or_create_chat_session(
        acc_id, "shop-001", "testuser", "buyer_unread", "买家"
    )
    chat_db.add_chat_message(sid, acc_id, "customer", "未读1", immediate=True)
    chat_db.add_chat_message(sid, acc_id, "customer", "未读2", immediate=True)
    chat_db.mark_chat_messages_read(sid)
    chat_db.add_chat_message(sid, acc_id, "customer", "新未读", immediate=True)
    chat_db.add_chat_message(sid, acc_id, "agent", "客服", immediate=True)
    assert chat_db.count_unread_buyer_messages(sid) == 1


def test_get_total_unread_chat(chat_db):
    acc_id = _account_id(chat_db)
    sid = chat_db.get_or_create_chat_session(
        acc_id, "shop-001", "testuser", "buyer_total", "买家"
    )
    assert chat_db.get_total_unread_chat() == 0
    chat_db.add_chat_message(sid, acc_id, "customer", "hi", immediate=True)
    assert chat_db.get_total_unread_chat() == 1
    chat_db.mark_chat_messages_read(sid)
    assert chat_db.get_total_unread_chat() == 0


def test_reopen_chat_session(chat_db):
    acc_id = _account_id(chat_db)
    sid = chat_db.get_or_create_chat_session(
        acc_id, "shop-001", "testuser", "buyer_reopen", "买家"
    )
    chat_db.close_chat_session(sid)
    row = chat_db.get_chat_session_by_id(sid)
    assert row["status"] == "closed"
    assert chat_db.reopen_chat_session(sid) is True
    row = chat_db.get_chat_session_by_id(sid)
    assert row["status"] == "active"
    assert chat_db.reopen_chat_session(sid) is False


def test_get_chat_session_summaries_all_status(chat_db):
    acc_id = _account_id(chat_db)
    sid_active = chat_db.get_or_create_chat_session(
        acc_id, "shop-001", "testuser", "buyer_active", "活跃"
    )
    sid_closed = chat_db.get_or_create_chat_session(
        acc_id, "shop-001", "testuser", "buyer_closed", "结案"
    )
    chat_db.close_chat_session(sid_closed)
    active_only = chat_db.get_chat_session_summaries(account_id=acc_id, status="active")
    all_rows = chat_db.get_chat_session_summaries(account_id=acc_id, status=None)
    assert len(active_only) == 1
    assert len(all_rows) == 2
    assert {r["id"] for r in all_rows} == {sid_active, sid_closed}


def test_get_chat_session_summaries_and_by_buyer(chat_db):
    acc_id = _account_id(chat_db)
    sid = chat_db.get_or_create_chat_session(
        acc_id, "shop-001", "testuser", "buyer_sum", "摘要买家"
    )
    chat_db.add_chat_message(
        sid, acc_id, "customer", "最后一条很长" * 20, immediate=True
    )

    summaries = chat_db.get_chat_session_summaries(account_id=acc_id)
    assert len(summaries) == 1
    row = summaries[0]
    assert row["id"] == sid
    assert row["buyer_nickname"] == "摘要买家"
    assert row["unread_count"] == 1
    assert len(row["last_message"]) <= 50

    by_buyer = chat_db.get_chat_session_by_buyer(acc_id, "buyer_sum")
    assert by_buyer is not None
    assert by_buyer["id"] == sid
    assert by_buyer["unread_count"] == 1


def test_add_chat_message_dedup_message_id(chat_db):
    acc_id = _account_id(chat_db)
    sid = chat_db.get_or_create_chat_session(
        acc_id, "shop-001", "testuser", "buyer_dedup", "买家"
    )
    first = chat_db.add_chat_message(
        sid, acc_id, "customer", "原内容", message_id="m-dup", immediate=True
    )
    second = chat_db.add_chat_message(
        sid, acc_id, "customer", "重复", message_id="m-dup", immediate=True
    )
    assert first is not None
    assert second == first


def test_list_all_accounts_for_chat(chat_db):
    rows = chat_db.list_all_accounts_for_chat()
    assert len(rows) == 1
    assert rows[0]["platform_shop_id"] == "shop-001"
    assert rows[0]["username"] == "testuser"


def test_add_chat_messages_batch_dedup(chat_db):
    from dataclasses import dataclass

    @dataclass
    class _Item:
        session_id: int
        account_id: int
        sender_type: str
        content: str
        message_id: str | None = None
        content_type: str = "text"
        image_url: str | None = None
        increment_unread: bool = False
        sent_at: object = None

    acc_id = _account_id(chat_db)
    sid = chat_db.get_or_create_chat_session(
        acc_id, "shop-001", "testuser", "buyer_batch", "买家"
    )
    chat_db.add_chat_message(
        sid, acc_id, "customer", "已有", message_id="dup-1", immediate=True
    )
    batch = [
        _Item(sid, acc_id, "customer", "跳过", message_id="dup-1"),
        _Item(sid, acc_id, "customer", "新消息", message_id="new-1"),
        _Item(sid, acc_id, "customer", "批内重复", message_id="batch-dup"),
        _Item(sid, acc_id, "customer", "批内重复2", message_id="batch-dup"),
    ]
    written = chat_db.add_chat_messages_batch(batch)
    assert written == 2
    assert chat_db.get_chat_message_count(sid) == 3
