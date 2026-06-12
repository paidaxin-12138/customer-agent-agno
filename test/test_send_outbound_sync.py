"""同步出站 Outbox 封装。"""
from unittest.mock import MagicMock, patch

from Message.handlers.channel_send import send_image_sync


def test_send_image_sync_uses_outbox():
    with patch(
        "Message.handlers.channel_send._prepare_outbox",
        return_value=7,
    ), patch(
        "Message.handlers.channel_send._claim_outbox_before_mms",
        return_value=None,
    ), patch(
        "utils.outbound_mms_dispatch.execute_outbox_mms_send",
        return_value=(True, ""),
    ), patch(
        "Message.handlers.channel_send._finalize_outbox_success",
    ) as mock_finalize:
        ok, err = send_image_sync(
            "s1",
            "u1",
            "b1",
            image_url="https://img.example.com/x.png",
            metadata={"username": "login1"},
        )
    assert ok is True
    assert err == ""
    mock_finalize.assert_called_once()
