# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""Stage 生命周期：回收、超时、await_confirm、意图重置、全阶段转人工。"""
from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.context import ChannelType, Context, ContextType
from Message.handlers.address_change_handler import (
    AddressChangeHandler,
    _is_address_cancel_message,
    _is_address_confirm_message,
)
from Message.handlers.ai_handler import AIReplyHandler
from Message.handlers.keyword_handler import KeywordDetectionHandler
from Message.handlers.order_logistics_handler import OrderLogisticsHandler
from Agent.CustomerAgent.conversation_memory import (
    TaskState,
    commit_handler_session_from_context,
    get_current_stage,
    load_task_state,
    maybe_expire_task_stage,
    normalize_session_stage,
    update_session_state,
)
from utils.intent_stage_reset import should_reset_stage_for_intent, try_intent_stage_reset


def _ctx(text: str = "你好", *, raw_stage: str = "idle") -> Context:
    kwargs = type(
        "Kwargs",
        (),
        {
            "from_uid": "b1",
            "shop_id": "s1",
            "user_id": "u1",
            "raw_data": {"_session_stage": raw_stage},
        },
    )()
    return Context(
        type=ContextType.TEXT,
        content=text,
        channel_type=ChannelType.PINDUODUO,
        kwargs=kwargs,
    )


def test_commit_enter_business_flow_from_idle_clears_stale_slots():
    ctx = _ctx("改收货地址")
    meta = {"shop_id": "s1", "user_id": "u1", "from_uid": "b1", "channel_name": "pinduoduo"}
    mem = {
        "task_state_json": json.dumps(
            {
                "stage": "idle",
                "slots": {"order_sn": "old-order", "phone": "13800138000"},
            }
        )
    }
    mock_db = MagicMock()
    mock_db.get_account.return_value = {"id": 1}
    mock_db.get_chat_session_by_buyer.return_value = {"id": 42}
    mock_db.get_session_memory.return_value = mem

    with patch("database.db_manager.db_manager", mock_db):
        commit_handler_session_from_context(
            ctx,
            meta,
            stage="address_change",
            intent="address_change",
            slots={"phone": "13900139000"},
            source_handler="Test",
        )
    written = json.loads(mock_db.update_session_memory.call_args.kwargs["task_state_json"])
    assert written["stage"] == "address_change"
    assert written["slots"] == {"phone": "13900139000"}


def test_commit_release_stage_sets_idle_and_clears_slots():
    ctx = _ctx()
    meta = {"shop_id": "s1", "user_id": "u1", "from_uid": "b1", "channel_name": "pinduoduo"}
    mem = {
        "task_state_json": json.dumps(
            {
                "stage": "address_change",
                "slots": {"order_sn": "250101-1", "phone": "13800138000"},
                "pending_confirm": ["收货信息"],
            }
        )
    }
    mock_db = MagicMock()
    mock_db.get_account.return_value = {"id": 1}
    mock_db.get_chat_session_by_buyer.return_value = {"id": 42}
    mock_db.get_session_memory.return_value = mem

    with patch("database.db_manager.db_manager", mock_db):
        commit_handler_session_from_context(
            ctx,
            meta,
            stage="address_change",
            release_stage=True,
            source_handler="Test",
        )
    assert meta["_session_stage"] == "idle"
    written = json.loads(mock_db.update_session_memory.call_args.kwargs["task_state_json"])
    assert written["stage"] == "idle"
    assert written.get("slots") == {}
    assert written.get("pending_confirm") == []


def test_maybe_expire_task_stage_resets_old_business_stage():
    task = TaskState(stage="logistics", stage_updated_at=time.time() - 7200)
    with patch(
        "Agent.CustomerAgent.conversation_memory._stage_idle_timeout_sec",
        return_value=1800,
    ):
        assert maybe_expire_task_stage(task) is True
    assert task.stage == "idle"
    assert task.slots == {}


def test_load_task_state_persists_expired_stage():
    old_ts = time.time() - 7200
    mem = {
        "task_state_json": json.dumps(
            {"stage": "after_sales", "stage_updated_at": old_ts}
        )
    }
    mock_db = MagicMock()
    mock_db.get_session_memory.return_value = mem

    with patch("database.db_manager.db_manager", mock_db), patch(
        "Agent.CustomerAgent.conversation_memory._stage_idle_timeout_sec",
        return_value=1800,
    ):
        task = load_task_state(99)
    assert task.stage == "idle"
    mock_db.update_session_memory.assert_called()


def test_await_confirm_confirm_and_cancel():
    assert _is_address_confirm_message("确认改址")
    assert _is_address_cancel_message("取消不改了")


@pytest.mark.parametrize(
    "stage,text,expected",
    [
        ("address_change", "多少钱", True),
        ("address_change", "改收货地址", False),
        ("idle", "多少钱", False),
    ],
)
def test_should_reset_stage_for_product_question(stage, text, expected):
    assert (
        should_reset_stage_for_intent(stage, "price", text)
        is expected
    )


def test_should_reset_after_sales_on_general_chat():
    assert should_reset_stage_for_intent("after_sales", "general", "你好") is True
    assert should_reset_stage_for_intent("after_sales", "after_sales", "要退款") is False


def test_try_intent_stage_reset_from_after_sales_general():
    ctx = _ctx("你好", raw_stage="after_sales")
    meta = {"shop_id": "s1", "user_id": "u1", "from_uid": "b1", "channel_name": "pinduoduo"}
    mock_db = MagicMock()
    mock_db.get_account.return_value = {"id": 1}
    mock_db.get_chat_session_by_buyer.return_value = {"id": 3}
    mock_db.get_session_memory.return_value = {
        "task_state_json": json.dumps({"stage": "after_sales", "intent": "after_sales"})
    }

    with patch("database.db_manager.db_manager", mock_db), patch(
        "Agent.CustomerAgent.conversation_memory.get_current_stage",
        return_value="after_sales",
    ):
        assert try_intent_stage_reset(ctx, meta, message_text="你好") is True
    assert meta["_session_stage"] == "idle"


def test_keyword_handler_allowed_in_address_change_stage():
    ctx = _ctx("转人工", raw_stage="address_change")
    with patch(
        "Agent.CustomerAgent.conversation_memory.get_current_stage",
        return_value="address_change",
    ):
        assert KeywordDetectionHandler().can_handle(ctx) is True


def test_ai_handler_allowed_after_intent_reset_stage():
    ctx = _ctx("多少钱", raw_stage="idle")
    with patch(
        "Agent.CustomerAgent.conversation_memory.get_current_stage",
        return_value="idle",
    ):
        assert AIReplyHandler(bot=None).can_handle(ctx) is True


@pytest.mark.asyncio
async def test_address_change_confirm_releases_stage():
    handler = AddressChangeHandler()
    ctx = _ctx("确认", raw_stage="await_confirm")
    meta = {"shop_id": "s1", "user_id": "u1", "from_uid": "b1"}
    mock_db = MagicMock()
    mock_db.get_account.return_value = {"id": 1}
    mock_db.get_chat_session_by_buyer.return_value = {"id": 7}
    mock_db.get_session_memory.return_value = {
        "task_state_json": json.dumps({"stage": "await_confirm"})
    }

    with patch(
        "Agent.CustomerAgent.conversation_memory.get_current_stage",
        return_value="await_confirm",
    ), patch("database.db_manager.db_manager", mock_db), patch.object(
        handler, "_send_reply", new_callable=AsyncMock
    ):
        ok = await handler.handle(ctx, meta)
    assert ok is True
    written = json.loads(mock_db.update_session_memory.call_args.kwargs["task_state_json"])
    assert written["stage"] == "idle"


def test_try_intent_stage_reset_updates_cache():
    ctx = _ctx("多少钱", raw_stage="address_change")
    meta = {"shop_id": "s1", "user_id": "u1", "from_uid": "b1", "channel_name": "pinduoduo"}
    mock_db = MagicMock()
    mock_db.get_account.return_value = {"id": 1}
    mock_db.get_chat_session_by_buyer.return_value = {"id": 3}
    mock_db.get_session_memory.return_value = {
        "task_state_json": json.dumps({"stage": "address_change", "intent": "general"})
    }

    with patch("database.db_manager.db_manager", mock_db), patch(
        "Agent.CustomerAgent.conversation_memory.get_current_stage",
        return_value="address_change",
    ):
        assert try_intent_stage_reset(ctx, meta, message_text="多少钱") is True
    assert meta["_session_stage"] == "idle"


def test_update_session_state_sets_stage_updated_at():
    mem = {"task_state_json": json.dumps({"stage": "idle", "stage_updated_at": 0})}
    mock_db = MagicMock()
    mock_db.get_session_memory.return_value = mem

    with patch("database.db_manager.db_manager", mock_db):
        task = update_session_state(1, stage="logistics", source_handler="T")
    assert task.stage == "logistics"
    written = json.loads(mock_db.update_session_memory.call_args.kwargs["task_state_json"])
    assert written.get("stage_updated_at", 0) > 0


def test_logistics_commit_releases_stage():
    ctx = _ctx("查物流")
    meta = {"shop_id": "s1", "user_id": "u1", "from_uid": "b1", "channel_name": "pinduoduo"}
    mock_db = MagicMock()
    mock_db.get_account.return_value = {"id": 1}
    mock_db.get_chat_session_by_buyer.return_value = {"id": 5}
    mock_db.get_session_memory.return_value = {
        "task_state_json": json.dumps({"stage": "logistics"})
    }

    with patch("database.db_manager.db_manager", mock_db):
        OrderLogisticsHandler._commit_logistics_state(
            ctx, meta, order_sn="250105-123456789012345", release_stage=True
        )
    written = json.loads(mock_db.update_session_memory.call_args.kwargs["task_state_json"])
    assert written["stage"] == "idle"


def test_normalize_session_stage_maps_legacy_general_to_idle():
    assert normalize_session_stage("general") == "idle"
    assert normalize_session_stage("greeting") == "idle"
    assert TaskState.from_dict({"stage": "general", "intent": "general"}).stage == "idle"


def test_ai_handler_can_handle_when_db_stage_is_general():
    ctx = _ctx("你好", raw_stage="general")
    meta = {"_session_stage": "general"}
    assert get_current_stage(ctx, meta) == "idle"
    handler = AIReplyHandler(bot=None)
    with patch(
        "Agent.CustomerAgent.conversation_memory.get_current_stage",
        return_value="idle",
    ):
        assert handler.can_handle(ctx) is True
