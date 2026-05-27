"""买家离线自动结案单元测试。"""
from unittest.mock import MagicMock, patch

from core.session_idle_closer import SessionIdleCloserService


def test_idle_closer_run_once_closes_and_notifies():
    svc = SessionIdleCloserService()
    with patch(
        "core.session_idle_closer.config.get",
        side_effect=lambda key, default=None: {
            "chat.session_idle_resolve_enabled": True,
            "chat.session_idle_resolve_minutes": 5,
        }.get(key, default),
    ):
        with patch(
            "core.session_idle_closer.db_manager.close_idle_chat_sessions",
            return_value=[(1, "buyer_uid", "pinduoduo:shop:cs")],
        ) as mock_close:
            hub = MagicMock()
            with patch(
                "core.session_idle_closer.get_conversation_hub",
                return_value=hub,
                create=True,
            ):
                with patch(
                    "ui.conversation_hub.get_conversation_hub",
                    return_value=hub,
                ):
                    n = svc.run_once()
    assert n == 1
    mock_close.assert_called_once()
    assert mock_close.call_args.kwargs["idle_seconds"] == 300
    hub.list_changed.emit.assert_called_once_with("pinduoduo:shop:cs")
