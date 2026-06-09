# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""ws_context 解析单测。"""
from __future__ import annotations

import json

from bridge.context import Context, ContextType
from Channel.pinduoduo.ws_context import context_struct_payload, parse_ws_raw_message


def test_context_struct_payload_from_json_string():
    inner = {"event": "ask_refund_card_push", "order_sn": "123"}
    ctx = Context(type=ContextType.MALL_CS, content=json.dumps(inner, ensure_ascii=False))
    payload = context_struct_payload(ctx)
    assert payload["event"] == "ask_refund_card_push"


def test_parse_ws_raw_message_invalid_json():
    assert parse_ws_raw_message("not-json") is None


def test_parse_ws_raw_message_empty():
    assert parse_ws_raw_message("   ") is None
