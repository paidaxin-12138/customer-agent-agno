"""send_structured_outbound 区分真发与 skipped:duplicate。"""
from unittest.mock import patch

import pytest

from utils.merchant_refund_apply_record import REFUND_GATE_SKIP_PREFIX


@pytest.mark.asyncio
async def test_refund_card_skipped_duplicate_flag():
    from Message.handlers import channel_send

    finalize_kwargs = {}

    def capture_finalize(**kwargs):
        finalize_kwargs.update(kwargs)

    with patch.object(channel_send, "_prepare_outbox", return_value=None), patch.object(
        channel_send, "_claim_outbox_before_mms"
    ), patch.object(
        channel_send, "_finalize_outbox_success", side_effect=capture_finalize
    ), patch(
        "utils.outbound_mms_dispatch.execute_outbox_mms_send",
        return_value=(True, REFUND_GATE_SKIP_PREFIX),
    ):
        ok, result = await channel_send.send_structured_outbound(
            "s1",
            "u1",
            "b1",
            content="[refund_apply] order=O1",
            message_kind="refund_apply_card",
            payload={"order_sn": "O1"},
            notify_watchdog=True,
        )

    assert ok is True
    assert isinstance(result, dict)
    assert result.get("skipped_duplicate") is True
    assert result.get("order_sn") == "O1"
    assert finalize_kwargs.get("record_receipt") is False
    assert finalize_kwargs.get("notify_watchdog") is False
    assert finalize_kwargs.get("mark_comfort_sent") is False
