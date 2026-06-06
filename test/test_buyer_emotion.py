"""买家情绪波动检测与处理器。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import Context, ContextType
from utils.buyer_emotion_intent import (
    build_emotion_alert_summary,
    detect_buyer_emotion,
)
from utils.buyer_emotion_tracker import record_emotion_alert, reset_emotion_alerts


def test_detect_buyer_emotion():
    assert detect_buyer_emotion("太差了，什么态度")
    assert detect_buyer_emotion("气死了还不发货")
    assert not detect_buyer_emotion("这款多少钱")


def test_build_emotion_summary():
    text = build_emotion_alert_summary("太差了", buyer_nickname="小明")
    assert "小明" in text
    assert "情绪波动" in text


def test_emotion_tracker_threshold():
    reset_emotion_alerts("sess:1")
    assert record_emotion_alert("sess:1") == 1
    assert record_emotion_alert("sess:1") == 2
    reset_emotion_alerts("sess:1")


@pytest.mark.asyncio
async def test_emotion_handler_first_alert_only_popup():
    from Message.handlers.buyer_emotion_handler import BuyerEmotionHandler

    reset_emotion_alerts("pdd:s:u:b")
    handler = BuyerEmotionHandler()
    ctx = Context(
        type=ContextType.TEXT,
        content="气死了什么态度",
        kwargs=MagicMock(shop_id="s", user_id="u", from_uid="b", nickname="买家A"),
    )
    meta = {"shop_id": "s", "user_id": "u", "from_uid": "b", "channel_name": "pinduoduo"}

    with patch(
        "Message.handlers.ai_reply_watchdog.resolve_session_key",
        return_value="pdd:s:u:b",
    ), patch(
        "core.human_assist_bus.emit_human_assist",
    ) as mock_emit, patch(
        "Message.handlers.buyer_emotion_handler.send_human_transfer_comfort",
        new_callable=AsyncMock,
    ) as mock_comfort:
        ok = await handler.handle(ctx, meta)

    assert ok is False
    mock_emit.assert_called_once()
    assert mock_emit.call_args.args[0] == "buyer_emotion_alert"
    mock_comfort.assert_not_awaited()


@pytest.mark.asyncio
async def test_emotion_handler_second_triggers_escalate():
    from Message.handlers.buyer_emotion_handler import BuyerEmotionHandler

    reset_emotion_alerts("pdd:s:u:b")
    record_emotion_alert("pdd:s:u:b")
    handler = BuyerEmotionHandler()
    ctx = Context(
        type=ContextType.TEXT,
        content="投诉你们",
        kwargs=MagicMock(shop_id="s", user_id="u", from_uid="b"),
    )
    meta = {"shop_id": "s", "user_id": "u", "from_uid": "b", "channel_name": "pinduoduo"}

    with patch(
        "Message.handlers.ai_reply_watchdog.resolve_session_key",
        return_value="pdd:s:u:b",
    ), patch(
        "core.human_assist_bus.emit_human_assist",
    ) as mock_emit, patch(
        "Message.handlers.buyer_emotion_handler.send_human_transfer_comfort",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_comfort, patch(
        "Message.handlers.buyer_emotion_handler.transfer_to_available_cs_async",
        new_callable=AsyncMock,
        return_value=False,
    ):
        ok = await handler.handle(ctx, meta)

    assert ok is True
    mock_comfort.assert_awaited_once()
    assert mock_emit.call_args.args[0] == "buyer_emotion_escalate"
