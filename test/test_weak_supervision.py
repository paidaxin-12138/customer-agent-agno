# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""弱监督模式：多账号 AI 优先、关闭转接前 Gate。"""
from unittest.mock import patch

from config_schema import ChatConfig
from utils import weak_supervision


def test_chat_config_schema_weak_supervision_field():
    model = ChatConfig(weak_supervision_enabled=True)
    assert model.weak_supervision_enabled is True


def test_weak_supervision_disables_transfer_gate(monkeypatch):
    monkeypatch.setattr(
        "utils.weak_supervision.get_config",
        lambda key, default=None: True if key == "chat.weak_supervision_enabled" else default,
    )
    assert weak_supervision.weak_supervision_enabled() is True
    assert weak_supervision.effective_inbound_transfer_gate() is False


def test_weak_supervision_default_ai_mode_true(monkeypatch):
    monkeypatch.setattr(
        "utils.weak_supervision.get_config",
        lambda key, default=None: True if key == "chat.weak_supervision_enabled" else default,
    )
    assert weak_supervision.default_ai_mode_for_account(99) is True


def test_gate_blocks_when_weak_supervision_off(monkeypatch):
    monkeypatch.setattr(
        "utils.weak_supervision.get_config",
        lambda key, default=None: (
            False
            if key == "chat.weak_supervision_enabled"
            else (True if key == "chat.inbound_transfer_gate_until_received" else default)
        ),
    )
    from utils.inbound_transfer_gate import should_block_handler_until_transfer
    from bridge.context import Context, ContextType
    from bridge.context import ChannelType

    ctx = Context(
        type=ContextType.TEXT,
        content="hi",
        channel_type=ChannelType.PINDUODUO,
    )
    with patch(
        "utils.inbound_transfer_gate.is_preferred_reception_seller",
        return_value=True,
    ), patch(
        "utils.inbound_transfer_gate.resolve_session_id",
        return_value=1,
    ), patch(
        "utils.inbound_transfer_gate.is_inbound_transferred",
        return_value=False,
    ):
        assert should_block_handler_until_transfer(ctx, {"shop_id": "s", "user_id": "u"}) is True
