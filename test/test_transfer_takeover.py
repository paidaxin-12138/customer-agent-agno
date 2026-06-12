# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""转接后强制接管：stage/ai_mode 与未回复入队。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.transfer_takeover import (
    apply_inbound_transfer_takeover,
    inbound_transfer_initial_ai_mode,
)


def test_inbound_transfer_initial_ai_mode_when_takeover_on(monkeypatch):
    monkeypatch.setattr(
        "utils.transfer_takeover.config.get",
        lambda key, default=None: {
            "chat.inbound_transfer_force_takeover": True,
            "chat.inbound_transfer_takeover_ai_mode": True,
            "chat.inbound_transfer_default_manual": True,
        }.get(key, default),
    )
    assert inbound_transfer_initial_ai_mode() is True


@pytest.mark.asyncio
async def test_takeover_enqueues_unreplied(monkeypatch):
    monkeypatch.setattr(
        "utils.transfer_takeover.config.get",
        lambda key, default=None: {
            "chat.inbound_transfer_force_takeover": True,
            "chat.inbound_transfer_takeover_ai_mode": True,
            "chat.inbound_transfer_enqueue_unreplied": True,
            "chat.inbound_transfer_default_manual": True,
            "chat.unreplied_buyer_max_parts": 3,
        }.get(key, default),
    )
    mock_db = MagicMock()
    mock_db.get_account.return_value = {"id": 1}
    mock_db.get_chat_session_by_buyer.return_value = {"id": 9}

    put_mock = AsyncMock(return_value="queued-1")

    with (
        patch("database.db_manager.db_manager", mock_db),
        patch(
            "utils.transfer_takeover._resolve_session_id",
            return_value=9,
        ),
        patch(
            "utils.unreplied_buyer_messages.get_unreplied_buyer_messages",
            return_value=["转接前买家问题"],
        ),
        patch(
            "Agent.CustomerAgent.conversation_memory.transition_session_stage"
        ) as mock_update,
        patch("database.session_store.set_ai_mode") as mock_ai,
        patch("Message.put_message", put_mock),
    ):
        ok = await apply_inbound_transfer_takeover(
            channel_name="pinduoduo",
            shop_id="570414651",
            seller_user_id="184046586",
            login_username="pdd57041465173",
            buyer_uid="4216881609",
            queue_name="pdd_570414651",
        )

    assert ok is True
    mock_ai.assert_called_once_with(9, True)
    mock_update.assert_called_once()
    call_kw = mock_update.call_args[1]
    assert call_kw.get("stage") == "after_sales"
    assert call_kw.get("intent") == "after_sales"
    assert call_kw.get("clear_flow_state") is True
    put_mock.assert_awaited_once()
