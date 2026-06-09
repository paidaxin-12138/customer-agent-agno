# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
import pytest

from bridge.context import ChannelType, Context, ContextType
from Message.handlers.fallback_reply import should_attempt_fallback


@pytest.mark.parametrize(
    "ctx_type,expected",
    [
        (ContextType.TEXT, True),
        (ContextType.SYSTEM_HINT, False),
        (ContextType.IMAGE, False),
    ],
)
def test_should_attempt_fallback_types(ctx_type, expected, monkeypatch):
    monkeypatch.setattr(
        "Message.handlers.fallback_reply.config.get",
        lambda key, default=None: True
        if key == "chat.unhandled_fallback_enabled"
        else default,
    )
    ctx = Context(type=ctx_type, content="hi", channel_type=ChannelType.PINDUODUO)
    assert should_attempt_fallback(ctx) is expected
