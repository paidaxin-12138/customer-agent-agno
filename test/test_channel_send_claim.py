"""outbox claim 争用时不破坏 processing/sent 行。"""
from unittest.mock import patch

import pytest

from Message.handlers.channel_send import (
    OUTBOX_CLAIM_CONTENTED,
    OUTBOX_CLAIM_ERROR,
    send_image_sync,
    send_structured_outbound,
)


@pytest.mark.asyncio
async def test_structured_outbound_claim_contended_no_mark_failed():
    with patch(
        "Message.handlers.channel_send._prepare_outbox",
        return_value=9,
    ), patch(
        "Message.handlers.channel_send._claim_outbox_before_mms",
        return_value=OUTBOX_CLAIM_CONTENTED,
    ), patch("database.outbound_outbox.mark_failed") as mock_failed:
        ok, result = await send_structured_outbound(
            "s1",
            "u1",
            "b1",
            content="hello",
            message_kind="text",
        )
    assert ok is False
    assert result == {
        "success": False,
        "error_msg": OUTBOX_CLAIM_CONTENTED,
    }
    mock_failed.assert_not_called()


def test_sync_outbound_claim_contended_no_mark_failed():
    with patch(
        "Message.handlers.channel_send._prepare_outbox",
        return_value=9,
    ), patch(
        "Message.handlers.channel_send._claim_outbox_before_mms",
        return_value=OUTBOX_CLAIM_CONTENTED,
    ), patch("database.outbound_outbox.mark_failed") as mock_failed:
        ok, err = send_image_sync(
            "s1",
            "u1",
            "b1",
            image_url="https://img.example.com/x.png",
            metadata={"username": "login1"},
        )
    assert ok is False
    assert err == OUTBOX_CLAIM_CONTENTED
    mock_failed.assert_not_called()


@pytest.mark.asyncio
async def test_structured_outbound_claim_error_distinct_code():
    with patch(
        "Message.handlers.channel_send._prepare_outbox",
        return_value=9,
    ), patch(
        "Message.handlers.channel_send._claim_outbox_before_mms",
        return_value=OUTBOX_CLAIM_ERROR,
    ):
        ok, result = await send_structured_outbound(
            "s1",
            "u1",
            "b1",
            content="hello",
            message_kind="text",
        )
    assert ok is False
    assert result == {"success": False, "error_msg": OUTBOX_CLAIM_ERROR}
