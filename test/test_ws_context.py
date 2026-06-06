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
