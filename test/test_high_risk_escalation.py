"""弱高风险二次直转逻辑。"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import Context, ContextType
from utils.high_risk_escalation import (
    detect_weak_high_risk_text,
    record_weak_high_risk,
    reset_weak_high_risk,
    should_direct_transfer_second_weak,
)


def test_detect_weak_high_risk():
    assert detect_weak_high_risk_text("用了之后有点过敏")
    assert detect_weak_high_risk_text("我要投诉你们")
    assert not detect_weak_high_risk_text("这款多少钱")


def test_second_turn_triggers_direct_transfer():
    reset_weak_high_risk("sess-a")
    assert not should_direct_transfer_second_weak("sess-a", "有点发痒")
    assert should_direct_transfer_second_weak("sess-a", "还是红肿")


def test_first_turn_does_not_direct_transfer():
    reset_weak_high_risk("sess-b")
    assert not should_direct_transfer_second_weak("sess-b", "皮肤发红担心过敏")
    assert record_weak_high_risk("sess-b", "普通追问") == 1


@pytest.mark.asyncio
async def test_keyword_allergy_blocks_ai_without_explicit_human():
    from Message.handlers.keyword_handler import KeywordDetectionHandler

    handler = KeywordDetectionHandler()
    ku = MagicMock(shop_id="s", user_id="u", from_uid="b")
    ctx = Context(type=ContextType.TEXT, content="用了过敏", kwargs=ku)
    meta = {"shop_id": "s", "user_id": "u", "from_uid": "b"}

    with patch(
        "Message.handlers.keyword_handler.send_human_transfer_comfort",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_comfort, patch(
        "core.human_assist_bus.emit_human_assist",
    ) as mock_emit, patch(
        "Message.handlers.keyword_handler.transfer_to_available_cs_async",
        new_callable=AsyncMock,
        return_value=False,
    ):
        handled = await handler.handle(ctx, meta)

    assert handled is True
    mock_comfort.assert_awaited_once()
    mock_emit.assert_called_once()


@pytest.mark.asyncio
async def test_ai_handler_second_weak_high_risk_skips_llm():
    from Message.handlers.ai_handler import AIReplyHandler

    handler = AIReplyHandler(bot=MagicMock())
    ku = MagicMock(shop_id="s", user_id="u", from_uid="b")
    ctx = Context(type=ContextType.TEXT, content="还是过敏红肿", kwargs=ku)
    meta = {
        "shop_id": "s",
        "user_id": "u",
        "from_uid": "b",
        "_outbound_comfort_sent": True,
    }

    reset_weak_high_risk("pdd:s:u:b")
    record_weak_high_risk("pdd:s:u:b", "第一次说过敏")

    with patch.object(
        handler, "_is_ai_mode_enabled", new_callable=AsyncMock, return_value=True
    ), patch.object(
        handler, "_direct_code_transfer", new_callable=AsyncMock, return_value=True
    ) as mock_direct, patch(
        "Message.handlers.ai_handler.resolve_session_key",
        return_value="pdd:s:u:b",
    ), patch.object(
        handler, "_get_ai_reply_with_sync_retry", new_callable=AsyncMock
    ) as mock_llm:
        ok = await handler.handle(ctx, meta)

    assert ok is True
    mock_direct.assert_awaited_once()
    mock_llm.assert_not_called()
