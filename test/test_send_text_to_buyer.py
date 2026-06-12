"""send_text_to_buyer 委托 send_structured_outbound。"""
from unittest.mock import AsyncMock, patch

import pytest

from Message.handlers.channel_send import send_text_to_buyer


@pytest.mark.asyncio
async def test_send_text_delegates_to_structured_outbound():
    with patch(
        "Message.handlers.channel_send.send_structured_outbound",
        new_callable=AsyncMock,
        return_value=(True, {"success": True}),
    ) as mock_send:
        ok = await send_text_to_buyer(
            "shop1",
            "user1",
            "buyer1",
            "你好",
            metadata={"session_id": 1},
        )
    assert ok is True
    mock_send.assert_awaited_once()
    kwargs = mock_send.await_args.kwargs
    assert kwargs["message_kind"] == "text"
    assert kwargs["content"] == "你好"
