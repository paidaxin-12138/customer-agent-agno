"""转接入库时 ai_mode 与截流配置一致。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from database.chat_persist import persist_inbound_transfer_from_context


def test_persist_transfer_sets_ai_mode_when_takeover(monkeypatch):
    monkeypatch.setattr(
        "utils.transfer_takeover.config.get",
        lambda key, default=None: {
            "chat.inbound_transfer_force_takeover": True,
            "chat.inbound_transfer_takeover_ai_mode": True,
            "chat.inbound_transfer_default_manual": True,
        }.get(key, default),
    )
    mock_db = MagicMock()
    mock_db.get_account.return_value = {"id": 1}
    mock_db.get_or_create_chat_session.return_value = 42
    mock_db.is_active_chat = MagicMock(return_value=False)

    with patch("database.db_manager.db_manager", mock_db):
        persist_inbound_transfer_from_context(
            "pinduoduo",
            "570414651",
            "184046586",
            "test_user",
            "4216881609",
            "买家",
            "[会话已转接]",
            "mid1",
            0.0,
        )

    mock_db.set_session_ai_mode.assert_called_once_with(42, True)
