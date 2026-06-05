"""接待号仅在收到 TRANSFER 后才走责任链截流。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from bridge.context import ChannelType, Context, ContextType
from bridge.context import PinduoduoKwargs
from utils.inbound_transfer_gate import (
    default_ai_mode_for_new_session,
    should_block_handler_until_transfer,
)


def _buyer_context(*, shop_id: str = "722406697", user_id: str = "174053423") -> Context:
    return Context(
        type=ContextType.TEXT,
        content="你好",
        channel_type=ChannelType.PINDUODUO,
        kwargs=PinduoduoKwargs(
            from_user="user",
            from_uid="123456",
            to_user="mall_cs",
            shop_id=shop_id,
            user_id=user_id,
        ),
    )


def test_default_ai_mode_false_for_preferred_reception(monkeypatch):
    monkeypatch.setattr(
        "utils.inbound_transfer_gate.get_config",
        lambda key, default=None: True
        if key == "chat.inbound_transfer_gate_until_received"
        else default,
    )
    monkeypatch.setattr(
        "utils.inbound_transfer_gate.is_preferred_reception_account_id",
        lambda _aid: True,
    )
    assert default_ai_mode_for_new_session(3) is False


def test_gate_blocks_preferred_until_transferred(monkeypatch):
    monkeypatch.setattr(
        "utils.inbound_transfer_gate.gate_until_transfer_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "utils.inbound_transfer_gate.is_preferred_reception_seller",
        lambda _s, _u: True,
    )
    monkeypatch.setattr(
        "utils.inbound_transfer_gate.resolve_session_id",
        lambda _c, _m: 99,
    )
    monkeypatch.setattr(
        "utils.inbound_transfer_gate.is_inbound_transferred",
        lambda _sid: False,
    )
    ctx = _buyer_context()
    meta = {"shop_id": "722406697", "user_id": "174053423", "from_uid": "123456"}
    assert should_block_handler_until_transfer(ctx, meta) is True


def test_gate_allows_after_transferred(monkeypatch):
    monkeypatch.setattr(
        "utils.inbound_transfer_gate.gate_until_transfer_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "utils.inbound_transfer_gate.is_preferred_reception_seller",
        lambda _s, _u: True,
    )
    monkeypatch.setattr(
        "utils.inbound_transfer_gate.resolve_session_id",
        lambda _c, _m: 99,
    )
    monkeypatch.setattr(
        "utils.inbound_transfer_gate.is_inbound_transferred",
        lambda _sid: True,
    )
    ctx = _buyer_context()
    meta = {"shop_id": "722406697", "user_id": "174053423", "from_uid": "123456"}
    assert should_block_handler_until_transfer(ctx, meta) is False


def test_persist_transfer_marks_inbound_only(monkeypatch):
    mock_db = MagicMock()
    mock_db.get_account.return_value = {"id": 1}
    mock_db.get_or_create_chat_session.return_value = 42
    mock_db.is_active_chat = MagicMock(return_value=False)

    with (
        patch("database.db_manager.db_manager", mock_db),
        patch("utils.inbound_transfer_gate.mark_inbound_transferred") as mark_mock,
    ):
        from database.chat_persist import persist_inbound_transfer_from_context

        persist_inbound_transfer_from_context(
            "pinduoduo",
            "722406697",
            "174053423",
            "test_user",
            "4216881609",
            "买家",
            "[会话已转接]",
            "mid1",
            0.0,
        )

    mark_mock.assert_called_once_with(42)
    mock_db.set_session_ai_mode.assert_not_called()
