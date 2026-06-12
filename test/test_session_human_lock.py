"""6A：转人工后 ai_mode=False。"""
from unittest.mock import MagicMock, patch

from utils.session_human_lock import lock_session_to_human


def test_lock_session_sets_ai_mode_false():
    meta = {"shop_id": "s", "user_id": "u", "from_uid": "b"}
    with patch(
        "database.session_store.lock_session_human_atomic",
        return_value=True,
    ) as mock_ai, patch(
        "database.session_store.refresh_metadata_session",
    ), patch(
        "database.session_store.resolve_session_id_from_context",
        return_value=42,
    ), patch(
        "Message.handlers.ai_reply_watchdog.resolve_session_key",
        return_value="pdd:s:u:b",
    ), patch(
        "core.turn_abort.turn_abort_registry.abort_active_turn",
        return_value=True,
    ):
        ok = lock_session_to_human(context=MagicMock(), metadata=meta, reason="test")
    assert ok is True
    mock_ai.assert_called_once_with(42)
    assert meta.get("ai_mode") is False


def test_lock_returns_true_when_refresh_fails_but_db_locked():
    meta = {"shop_id": "s", "user_id": "u", "from_uid": "b"}
    with patch(
        "database.session_store.lock_session_human_atomic",
        return_value=True,
    ), patch(
        "database.session_store.refresh_metadata_session",
        side_effect=RuntimeError("refresh boom"),
    ), patch(
        "database.session_store.resolve_session_id_from_context",
        return_value=42,
    ), patch(
        "Message.handlers.ai_reply_watchdog.resolve_session_key",
        return_value="pdd:s:u:b",
    ), patch(
        "core.turn_abort.turn_abort_registry.abort_active_turn",
        return_value=True,
    ):
        ok = lock_session_to_human(context=MagicMock(), metadata=meta, reason="test")
    assert ok is True
    assert meta.get("ai_mode") is False
    assert meta.get("_human_locked") is True
