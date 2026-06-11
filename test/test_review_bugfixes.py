"""Bugbot review 修复回归测试。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import ChannelType, Context, ContextType
from core.turn_abort import TurnAborted


def _ctx_text(content: str = "转人工") -> Context:
    kwargs = type(
        "Kwargs",
        (),
        {
            "from_uid": "buyer_1",
            "from_user": "user",
            "to_user": "mall_cs",
            "shop_id": "shop_1",
            "user_id": "user_1",
            "username": "test_cs",
            "nickname": "买家A",
            "timestamp": None,
            "msg_id": None,
        },
    )()
    return Context(
        type=ContextType.TEXT,
        content=content,
        channel_type=ChannelType.PINDUODUO,
        kwargs=kwargs,
    )


def test_dismiss_watchdog_requires_explicit_flag():
    from Message.core.consumer import _dismiss_watchdog_if_handler_resolved_without_outbound

    metadata = {
        "_watchdog_epoch": 1,
        "handler_already_processed": True,
    }
    with patch(
        "Message.handlers.channel_send.notify_outbound_from_metadata"
    ) as notify:
        _dismiss_watchdog_if_handler_resolved_without_outbound(
            _ctx_text(), metadata, processed=True
        )
        notify.assert_not_called()

    metadata["_handler_resolved_without_outbound"] = True
    with patch(
        "Message.handlers.channel_send.notify_outbound_from_metadata"
    ) as notify:
        _dismiss_watchdog_if_handler_resolved_without_outbound(
            _ctx_text(), metadata, processed=True
        )
        notify.assert_called_once()


@pytest.mark.asyncio
async def test_image_video_handler_stops_chain_but_keeps_watchdog_on_send_fail():
    from Message.handlers.image_video_handler import ImageVideoHumanHandler
    from Message.core.consumer import _dismiss_watchdog_if_handler_resolved_without_outbound

    handler = ImageVideoHumanHandler()
    metadata = {
        "shop_id": "1",
        "user_id": "u",
        "from_uid": "b",
        "_watchdog_epoch": 1,
        "handler_already_processed": True,
    }
    context = Context(
        type=ContextType.IMAGE,
        content="http://img",
        channel_type=ChannelType.PINDUODUO,
        kwargs=type("Kwargs", (), metadata)(),
    )
    with patch.object(
        handler, "send_text_to_buyer", new_callable=AsyncMock, return_value=False
    ), patch("core.human_assist_bus.emit_human_assist"), patch.object(
        handler, "log_message", new_callable=AsyncMock
    ):
        ok = await handler.handle(context, metadata)
    assert ok is True
    assert not metadata.get("_handler_resolved_without_outbound")
    with patch(
        "Message.handlers.channel_send.notify_outbound_from_metadata"
    ) as notify:
        _dismiss_watchdog_if_handler_resolved_without_outbound(
            context, metadata, processed=True
        )
        notify.assert_not_called()


def test_fetch_mall_products_paginated_propagates_turn_aborted():
    from Agent.CustomerAgent.tools.get_product_list import _fetch_mall_products_paginated

    pm = MagicMock()
    pm.get_product_list.return_value = {
        "success": True,
        "products": [{"goods_id": 1}],
        "total": 1,
    }
    with patch(
        "core.turn_abort.check_turn_abort",
        side_effect=[None, TurnAborted("superseded")],
    ), patch(
        "scripts.sync_goods_to_kb._should_fetch_next_goods_page",
        return_value=True,
    ):
        with pytest.raises(TurnAborted):
            _fetch_mall_products_paginated(pm, max_pages=3)


def test_offload_tool_passes_abort_signal_to_worker_thread():
    import threading
    import time

    from core.turn_abort import TurnAbortRegistry, set_current_turn_abort, reset_current_turn_abort
    from utils.agno_tool_offload import offload_tool

    reg = TurnAbortRegistry()
    sig = reg.begin_turn("s/u/b")
    tok = set_current_turn_abort(sig)
    seen: list[str] = []

    @offload_tool
    def _paginated_tool() -> str:
        from core.turn_abort import check_turn_abort

        time.sleep(0.05)
        check_turn_abort()
        seen.append("ran")
        return "ok"

    def _abort_later() -> None:
        time.sleep(0.02)
        sig.abort("superseded_by_new_inbound")

    threading.Thread(target=_abort_later, daemon=True).start()
    try:
        result = _paginated_tool()
    finally:
        reset_current_turn_abort(tok)

    assert "中断" in result
    assert seen == []


def test_record_from_context_falls_back_to_memory_when_sync_fails():
    from ui.conversation_hub import ConversationHub

    hub = ConversationHub()
    context = _ctx_text("你好")
    emitted = {"n": 0}

    def _capture_emit(*_a, **_k):
        emitted["n"] += 1

    hub._emit_hub_updates = _capture_emit  # type: ignore[method-assign]
    with patch(
        "database.chat_persist.persist_customer_from_context"
    ), patch(
        "database.chat_message_buffer.flush_chat_message_buffer"
    ), patch.object(hub, "_sync_from_db", return_value=False):
        hub.record_from_context(
            "pinduoduo", "shop_1", "user_1", "test_cs", context
        )

    assert emitted["n"] == 1
    from ui.conversation_hub import make_account_key

    account_key = make_account_key("pinduoduo", "shop_1", "test_cs")
    with hub._lock:
        assert "buyer_1" in hub._by_account.get(account_key, {})
