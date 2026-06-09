# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""persist_ai_message / persist_human_message Hub 同步测试。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from database.chat_persist import persist_ai_message, persist_human_message


def test_persist_ai_message_syncs_hub():
    mock_db = MagicMock()
    mock_db.get_account.return_value = {"id": 1}
    mock_db.get_or_create_chat_session.return_value = 42
    hub = MagicMock()

    with (
        patch("database.db_manager.db_manager", mock_db),
        patch("ui.conversation_hub.get_conversation_hub", return_value=hub),
    ):
        sid = persist_ai_message(
            "pinduoduo",
            "570414651",
            "184046586",
            "shop1",
            "buyer-99",
            "AI 回复内容",
        )

    assert sid == 42
    mock_db.add_chat_message.assert_called_once()
    hub.notify_persisted_message.assert_called_once()
    call_kw = hub.notify_persisted_message.call_args
    assert call_kw[0][4] == "buyer-99"
    assert call_kw[1]["role"] == "ai"


def test_persist_human_message_syncs_hub():
    mock_db = MagicMock()
    mock_db.get_account.return_value = {"id": 1}
    mock_db.get_or_create_chat_session.return_value = 55
    hub = MagicMock()

    with (
        patch("database.db_manager.db_manager", mock_db),
        patch("ui.conversation_hub.get_conversation_hub", return_value=hub),
    ):
        sid = persist_human_message(
            "pinduoduo",
            "570414651",
            "184046586",
            "shop1",
            "buyer-88",
            "人工回复",
        )

    assert sid == 55
    hub.notify_persisted_message.assert_called_once()
    assert hub.notify_persisted_message.call_args[1]["role"] == "agent"
