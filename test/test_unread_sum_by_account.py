"""get_unread_sum_by_account 单条 SQL 汇总测试。"""
from __future__ import annotations

import pytest

import database.db_manager as dm_module
from database.db_manager import DatabaseManager


@pytest.fixture()
def chat_db(tmp_path, monkeypatch):
    DatabaseManager._instance = None
    path = str(tmp_path / "unread_sum_test.db")
    db = DatabaseManager(db_path=path)
    dm_module._db_instance = db
    db.add_shop("pinduoduo", "shop-001", "测试店", "")
    db.add_account("pinduoduo", "shop-001", "uid-001", "testuser", "pass")
    monkeypatch.setenv("CHAT_MESSAGE_BUFFER_DISABLE", "1")
    yield db
    dm_module._db_instance = None
    DatabaseManager._instance = None


def _account_id(db: DatabaseManager) -> int:
    return db.get_account("pinduoduo", "shop-001", "uid-001")["id"]


def test_get_unread_sum_by_account_empty(chat_db):
    assert chat_db.get_unread_sum_by_account() == {}


def test_get_unread_sum_by_account_counts(chat_db):
    aid = _account_id(chat_db)
    sid = chat_db.get_or_create_chat_session(
        aid, "shop-001", "testuser", "buyer1", "买家1"
    )
    chat_db.add_chat_message(sid, aid, "customer", "你好", immediate=True)
    chat_db.add_chat_message(sid, aid, "customer", "在吗", immediate=True)
    chat_db.add_chat_message(sid, aid, "agent", "您好", immediate=True)

    got = chat_db.get_unread_sum_by_account()
    assert got.get(aid) == 2


def test_get_unread_sum_by_account_ignores_read(chat_db):
    aid = _account_id(chat_db)
    sid = chat_db.get_or_create_chat_session(
        aid, "shop-001", "testuser", "buyer2", "买家2"
    )
    chat_db.add_chat_message(sid, aid, "customer", "已读", immediate=True)
    chat_db.mark_chat_messages_read(sid)

    assert chat_db.get_unread_sum_by_account().get(aid, 0) == 0
