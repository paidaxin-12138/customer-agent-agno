"""出站回执：卡顿/未入库时补偿门禁。"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from utils.outbound_receipt import (
    clear_outbound_receipt_cache_for_tests,
    has_recent_outbound_receipt,
    record_outbound_receipt,
)


def setup_function():
    clear_outbound_receipt_cache_for_tests()


def test_record_and_detect_recent_receipt():
    key = "pinduoduo:s1:u1:b1"
    record_outbound_receipt(key, buyer_uid="b1", shop_id="s1", user_id="u1")
    assert has_recent_outbound_receipt(key, within_sec=300) is True


def test_receipt_survives_cache_reload():
    key = "pinduoduo:s2:u2:b2"
    record_outbound_receipt(key)
    from utils import outbound_receipt as mod

    mod._loaded = False
    mod._cache.clear()
    assert has_recent_outbound_receipt(key, within_sec=300) is True


def test_reconcile_skips_when_receipt_on_disk(monkeypatch):
    from core.ws_reconnect_reconcile import _last_reconcile_fingerprint, reconcile_account_after_auth

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

    key = "pinduoduo:s1:u1:b1"
    record_outbound_receipt(key, buyer_uid="b1", shop_id="s1", user_id="u1")

    mock_db = MagicMock()
    mock_db.get_account.return_value = {"id": 1, "username": "cs"}
    mock_db.get_chat_sessions.return_value = [{"id": 9, "buyer_uid": "b1"}]

    with patch("database.db_manager.db_manager", mock_db), patch(
        "utils.unreplied_buyer_messages.get_unreplied_buyer_messages",
        return_value=["还在吗"],
    ), patch("core.ws_reconnect_reconcile._enqueue_context") as mock_enqueue, patch(
        "Message.handlers.ai_reply_watchdog.was_recently_replied",
        return_value=False,
    ):
        n = reconcile_account_after_auth(
            channel_name="pinduoduo",
            shop_id="s1",
            user_id="u1",
            username="cs",
            is_reconnect=True,
        )
    assert n == 0
    mock_enqueue.assert_not_called()
