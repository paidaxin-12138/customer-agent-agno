# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""session_store 单一数据源测试。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from database.session_store import (
    load_session_summary,
    resolve_session_id,
    resolve_session_id_from_context,
    sync_hub_session,
)
from bridge.context import ChannelType, Context, ContextType


@pytest.fixture(autouse=True)
def _clear_hub_accounts():
    yield


def test_resolve_session_id_from_context():
    ctx = Context(
        type=ContextType.TEXT,
        content="hi",
        channel_type=ChannelType.PINDUODUO,
        kwargs=type(
            "K",
            (),
            {
                "shop_id": "shop1",
                "user_id": "u1",
                "from_uid": "buyer1",
            },
        )(),
    )
    meta = {"channel_name": "pinduoduo", "shop_id": "shop1", "user_id": "u1", "from_uid": "buyer1"}
    row = {
        "id": 99,
        "account_id": 3,
        "buyer_uid": "buyer1",
        "buyer_nickname": "买家A",
        "last_message": "hello",
        "unread_count": 2,
        "ai_mode": False,
        "last_message_time": None,
        "updated_at": None,
    }
    with patch("database.db_manager.db_manager.get_account", return_value={"id": 3}), patch(
        "database.db_manager.db_manager.get_chat_session_by_buyer", return_value=row
    ):
        assert resolve_session_id_from_context(ctx, meta) == 99


def test_sync_hub_session_uses_db_unread():
    from ui.conversation_hub import ConversationHub
    from database.session_store import SessionSummary

    hub = ConversationHub()
    summary = SessionSummary(
        session_id=10,
        account_id=1,
        buyer_uid="b1",
        buyer_nickname="Nick",
        preview="last msg",
        unread_count=5,
        ai_mode=True,
        updated_at=1000.0,
    )
    with patch(
        "database.session_store.load_session_summary", return_value=summary
    ):
        sync_hub_session(hub, "acc_key", 1, 10)

    with hub._lock:
        st = hub._by_account.get("acc_key", {}).get("b1")
    assert st is not None
    assert st.unread_count == 5
    assert st.session_id == 10


def test_set_ai_mode_delegates_to_db():
    with patch("database.db_manager.db_manager.set_session_ai_mode", return_value=True) as m:
        from database.session_store import set_ai_mode

        assert set_ai_mode(5, False) is True
    m.assert_called_once_with(5, False)


def test_prime_metadata_includes_stage():
    meta: dict = {}
    ctx = Context(
        type=ContextType.TEXT,
        content="hi",
        channel_type=ChannelType.PINDUODUO,
        kwargs=type("K", (), {"shop_id": "s", "user_id": "u", "from_uid": "b"})(),
    )
    with patch(
        "database.session_store.resolve_session_id_from_context", return_value=11
    ), patch(
        "database.session_store.load_session_summary",
        return_value=__import__(
            "database.session_store", fromlist=["SessionSummary"]
        ).SessionSummary(
            session_id=11,
            account_id=1,
            buyer_uid="b",
            buyer_nickname="",
            preview="",
            unread_count=0,
            ai_mode=True,
            updated_at=0.0,
        ),
    ), patch("database.session_store.load_session_stage", return_value="logistics"):
        from database.session_store import prime_metadata_session

        prime_metadata_session(meta, ctx)
    assert meta["session_id"] == 11
    assert meta["ai_mode"] is True
    assert meta["_session_stage"] == "logistics"


def test_hub_record_uses_sync_from_db():
    """persist 后走 _sync_from_db，不再本地递增未读。"""
    from ui.conversation_hub import ConversationHub
    from bridge.context import PinduoduoKwargs

    hub = ConversationHub()
    ctx = Context(
        type=ContextType.TEXT,
        content="买家消息",
        channel_type=ChannelType.PINDUODUO,
        kwargs=PinduoduoKwargs(
            from_user="user",
            from_uid="buyer_x",
            nickname="买家X",
            shop_id="s1",
            user_id="u1",
            msg_id="m1",
        ),
    )
    with patch(
        "database.chat_persist.persist_customer_from_context", return_value=7
    ), patch.object(hub, "_sync_from_db", return_value=True) as mock_sync, patch(
        "utils.qt_threading.run_on_main_thread", side_effect=lambda fn: fn()
    ):
        hub.record_from_context("pinduoduo", "s1", "u1", "cs", ctx)

    mock_sync.assert_called_once()
