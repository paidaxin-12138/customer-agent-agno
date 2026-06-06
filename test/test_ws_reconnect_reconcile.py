"""WS 认证后消息补偿。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.ws_reconnect_reconcile import reconcile_account_after_auth


def test_reconcile_skips_duplicate_within_cooldown(monkeypatch):
    from core.ws_reconnect_reconcile import _last_reconcile_fingerprint

    _last_reconcile_fingerprint.clear()
    monkeypatch.setattr(
        "core.ws_reconnect_reconcile.ws_reconnect_reconcile_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "core.ws_reconnect_reconcile._enqueue_unreplied_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "core.mms_session_sync.mms_session_sync_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "core.ws_reconnect_reconcile._reconcile_cooldown_sec",
        lambda: 300,
    )

    mock_db = MagicMock()
    mock_db.get_account.return_value = {"id": 1, "username": "cs"}
    mock_db.get_chat_sessions.return_value = [{"id": 9, "buyer_uid": "b1"}]

    with patch("database.db_manager.db_manager", mock_db), patch(
        "utils.unreplied_buyer_messages.get_unreplied_buyer_messages",
        return_value=["还在吗"],
    ), patch("core.ws_reconnect_reconcile._enqueue_context") as mock_enqueue:
        n1 = reconcile_account_after_auth(
            channel_name="pinduoduo",
            shop_id="s1",
            user_id="u1",
            username="cs",
        )
        n2 = reconcile_account_after_auth(
            channel_name="pinduoduo",
            shop_id="s1",
            user_id="u1",
            username="cs",
        )
    assert n1 == 1
    assert n2 == 0
    assert mock_enqueue.call_count == 1


def test_reconcile_enqueues_unreplied_sessions(monkeypatch):
    from core.ws_reconnect_reconcile import _last_reconcile_fingerprint

    _last_reconcile_fingerprint.clear()
    monkeypatch.setattr(
        "core.ws_reconnect_reconcile.ws_reconnect_reconcile_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "core.ws_reconnect_reconcile._enqueue_unreplied_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "core.mms_session_sync.mms_session_sync_enabled",
        lambda: False,
    )

    mock_db = MagicMock()
    mock_db.get_account.return_value = {
        "id": 1,
        "username": "shop_cs",
    }
    mock_db.get_chat_sessions.return_value = [
        {"id": 9, "buyer_uid": "buyer1"},
    ]

    with patch("database.db_manager.db_manager", mock_db), patch(
        "utils.unreplied_buyer_messages.get_unreplied_buyer_messages",
        return_value=["还在吗"],
    ), patch(
        "core.ws_reconnect_reconcile._enqueue_context"
    ) as mock_enqueue:
        n = reconcile_account_after_auth(
            channel_name="pinduoduo",
            shop_id="s1",
            user_id="u1",
            username="cs1",
        )
    assert n == 1
    mock_enqueue.assert_called_once()
