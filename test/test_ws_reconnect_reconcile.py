# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""WS 认证后消息补偿。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.ws_reconnect_reconcile import reconcile_account_after_auth
from utils.outbound_receipt import clear_outbound_receipt_cache_for_tests


def setup_function():
    clear_outbound_receipt_cache_for_tests()


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
            is_reconnect=True,
        )
        n2 = reconcile_account_after_auth(
            channel_name="pinduoduo",
            shop_id="s1",
            user_id="u1",
            username="cs",
            is_reconnect=True,
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
            is_reconnect=True,
        )
    assert n == 1
    mock_enqueue.assert_called_once()


def test_reconcile_skips_cold_start_by_default(monkeypatch):
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
        "core.ws_reconnect_reconcile._compensate_on_cold_start",
        lambda: False,
    )

    mock_db = MagicMock()
    mock_db.get_account.return_value = {"id": 1, "username": "cs"}
    mock_db.get_chat_sessions.return_value = [{"id": 9, "buyer_uid": "b1"}]

    with patch("database.db_manager.db_manager", mock_db), patch(
        "utils.unreplied_buyer_messages.get_unreplied_buyer_messages",
        return_value=["还在吗"],
    ), patch("core.ws_reconnect_reconcile._enqueue_context") as mock_enqueue:
        n = reconcile_account_after_auth(
            channel_name="pinduoduo",
            shop_id="s1",
            user_id="u1",
            username="cs",
            is_reconnect=False,
        )
    assert n == 0
    mock_enqueue.assert_not_called()


def test_reconcile_mms_sync_disables_enqueue_new(monkeypatch):
    from core.ws_reconnect_reconcile import _last_reconcile_fingerprint

    _last_reconcile_fingerprint.clear()
    monkeypatch.setattr(
        "core.ws_reconnect_reconcile.ws_reconnect_reconcile_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "core.ws_reconnect_reconcile._enqueue_unreplied_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "core.mms_session_sync.mms_session_sync_enabled",
        lambda: True,
    )

    mock_db = MagicMock()
    mock_db.get_account.return_value = {"id": 1, "username": "cs"}

    with patch("database.db_manager.db_manager", mock_db), patch(
        "core.mms_session_sync.sync_mms_sessions_for_account"
    ) as mock_sync:
        reconcile_account_after_auth(
            channel_name="pinduoduo",
            shop_id="s1",
            user_id="u1",
            username="cs",
            is_reconnect=True,
        )
    mock_sync.assert_called_once_with(1, reconnect_boost=True, enqueue_new=False)


def test_reconcile_skips_when_recently_replied(monkeypatch):
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
        lambda: 120,
    )

    mock_db = MagicMock()
    mock_db.get_account.return_value = {"id": 1, "username": "cs"}
    mock_db.get_chat_sessions.return_value = [{"id": 9, "buyer_uid": "b1"}]

    import Message.handlers.ai_reply_watchdog as wd

    key = "pinduoduo:s1:u1:b1"
    wd.mark_delivered(key, 1)

    with patch("database.db_manager.db_manager", mock_db), patch(
        "utils.unreplied_buyer_messages.get_unreplied_buyer_messages",
        return_value=["还在吗"],
    ), patch("core.ws_reconnect_reconcile._enqueue_context") as mock_enqueue:
        n = reconcile_account_after_auth(
            channel_name="pinduoduo",
            shop_id="s1",
            user_id="u1",
            username="cs",
            is_reconnect=True,
        )
    assert n == 0
    mock_enqueue.assert_not_called()
