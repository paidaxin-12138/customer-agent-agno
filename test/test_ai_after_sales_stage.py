# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""AI Handler 在 after_sales stage 下是否可处理（配置开关）。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from bridge.context import Context, ContextType, ChannelType
from Message.handlers.ai_handler import AIReplyHandler


def _make_context() -> Context:
    return Context.create_pinduoduo_context(
        content="售后问题",
        msg_id="m1",
        from_user="user",
        from_uid="4216881609",
        to_user="mall_cs",
        to_uid="184046586",
        nickname="买家",
        timestamp="1710000000000",
        user_msg_type=ContextType.TEXT,
        shop_id="570414651",
        user_id="184046586",
        username="test",
        channel_type=ChannelType.PINDUODUO,
    )


def test_ai_handler_allowed_in_after_sales_when_config_on(monkeypatch):
    monkeypatch.setattr(
        "Message.handlers.ai_handler.config.get",
        lambda key, default=None: True
        if key == "chat.ai_allow_after_sales_stage"
        else default,
    )
    handler = AIReplyHandler(bot=MagicMock())
    ctx = _make_context()
    with patch(
        "Agent.CustomerAgent.conversation_memory.get_current_stage",
        return_value="after_sales",
    ):
        assert handler.can_handle(ctx) is True


def test_ai_handler_blocked_in_after_sales_when_config_off(monkeypatch):
    monkeypatch.setattr(
        "Message.handlers.ai_handler.config.get",
        lambda key, default=None: False
        if key == "chat.ai_allow_after_sales_stage"
        else default,
    )
    handler = AIReplyHandler(bot=MagicMock())
    ctx = _make_context()
    with patch(
        "Agent.CustomerAgent.conversation_memory.get_current_stage",
        return_value="after_sales",
    ):
        assert handler.can_handle(ctx) is False
