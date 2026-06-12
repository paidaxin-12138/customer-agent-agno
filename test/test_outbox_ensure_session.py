"""Outbox 发送前 ensure session（首条无 session_id）。"""
from unittest.mock import MagicMock, patch

from Message.handlers.channel_send import _resolve_outbox_ids


def test_resolve_outbox_ids_creates_session_when_missing():
    meta = {"shop_id": "shop1", "user_id": "seller1", "username": "login1"}
    with patch(
        "database.session_store.resolve_session_id_from_context",
        return_value=None,
    ), patch(
        "database.db_manager.db_manager.get_account",
        return_value={"id": 99, "username": "login1"},
    ), patch(
        "database.db_manager.db_manager.get_or_create_chat_session",
        return_value=123,
    ) as mock_create:
        sid, aid, ch, login = _resolve_outbox_ids(
            "shop1",
            "seller1",
            "buyer1",
            context=MagicMock(),
            metadata=meta,
        )
    assert sid == 123
    assert aid == 99
    assert meta["session_id"] == 123
    mock_create.assert_called_once()

