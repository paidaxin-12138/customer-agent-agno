"""Context.content 为 JSON 字符串时，结构化 mall 消息可正确解析。"""

import json

from bridge.context import Context, ContextType
from Channel.pinduoduo.pdd_chnnel import _context_struct_payload
from Channel.pinduoduo.utils.API.chat_orders import refund_card_push_expired


def test_context_struct_payload_from_json_string():
    inner = {
        "event": "ask_refund_card_push",
        "order_sn": "260527-006427778640457",
        "mstate_status": 1,
        "mstate_expire_text": "已过期",
        "state_expire_text": "已过期",
    }
    ctx = Context(type=ContextType.MALL_CS, content=json.dumps(inner, ensure_ascii=False))
    payload = _context_struct_payload(ctx)
    assert payload["event"] == "ask_refund_card_push"
    assert refund_card_push_expired(
        {"expire_text": payload.get("state_expire_text")},
        {
            "expire_text": payload.get("mstate_expire_text"),
            "status": payload.get("mstate_status"),
        },
    )


def test_mall_system_refund_expired_from_json_string():
    inner = {
        "event": "refund_card_expired",
        "user_id": "4216881609",
        "msg_id": "1779867492174",
        "status": 4,
    }
    ctx = Context(
        type=ContextType.MALL_SYSTEM_MSG,
        content=json.dumps(inner, ensure_ascii=False),
    )
    payload = _context_struct_payload(ctx)
    assert payload.get("event") == "refund_card_expired"
    assert payload.get("user_id") == "4216881609"
