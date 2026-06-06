"""会话 flow memory 重置与 Handler 摘要。"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from Agent.CustomerAgent.conversation_memory import (
    append_handler_turn_summary,
    reset_session_flow_memory,
    session_key_from_session_id,
)


def test_reset_session_flow_memory_writes_idle_defaults():
    mock_db = MagicMock()
    mock_db.update_session_memory.return_value = True
    mock_db.get_chat_session_by_id.return_value = {
        "id": 42,
        "account_id": 1,
        "platform_shop_id": "s1",
        "buyer_uid": "b1",
    }
    mock_db.get_account_row_by_id.return_value = {
        "channel_name": "pinduoduo",
        "platform_shop_id": "s1",
        "seller_user_id": "u1",
    }
    with patch("database.db_manager.db_manager", mock_db), patch(
        "utils.buyer_emotion_tracker.reset_emotion_alerts"
    ) as mock_emo:
        reset_session_flow_memory(42, source="Test")
    payload = json.loads(mock_db.update_session_memory.call_args.kwargs["task_state_json"])
    assert payload["stage"] == "idle"
    assert payload.get("slots") == {}
    mock_emo.assert_called_once_with("pinduoduo:s1:u1:b1")


def test_session_key_from_session_id():
    mock_db = MagicMock()
    mock_db.get_chat_session_by_id.return_value = {
        "account_id": 2,
        "platform_shop_id": "shop",
        "buyer_uid": "buyer",
    }
    mock_db.get_account_row_by_id.return_value = {
        "channel_name": "pinduoduo",
        "seller_user_id": "seller",
        "platform_shop_id": "shop",
    }
    with patch("database.db_manager.db_manager", mock_db):
        assert session_key_from_session_id(9) == "pinduoduo:shop:seller:buyer"


def test_append_handler_turn_summary_merges():
    mem = {"long_term_summary": json.dumps({"user_requests": [], "confirmed": []})}
    mock_db = MagicMock()
    mock_db.get_session_memory.return_value = mem
    mock_db.update_session_memory.return_value = True
    with patch("database.db_manager.db_manager", mock_db):
        append_handler_turn_summary(
            1, buyer_text="改地址", agent_text="好的亲，已记录"
        )
    written = json.loads(mock_db.update_session_memory.call_args.kwargs["long_term_summary"])
    assert "改地址" in written["user_requests"]
    assert written["confirmed"]
