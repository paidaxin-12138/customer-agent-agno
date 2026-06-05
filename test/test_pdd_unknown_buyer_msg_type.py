"""转接后买家未知 WS type 应映射为 TEXT 而非 SYSTEM_STATUS。"""
from __future__ import annotations

from bridge.context import ContextType
from Channel.pinduoduo.pdd_message import PDDChatMessage


def test_unknown_user_msg_type_from_buyer_maps_to_text():
    raw = {
        "response": "push",
        "message": {
            "type": 19,
            "msg_id": "m-unknown-19",
            "content": "转接后卡片内容",
            "from": {"role": "user", "uid": "4216881609"},
            "to": {"role": "mall_cs", "uid": "184046586"},
            "time": 1710000000000,
        },
    }
    pdd = PDDChatMessage(raw)
    assert pdd.user_msg_type == ContextType.TEXT
    assert pdd.content == "转接后卡片内容"
    assert pdd.from_user == "user"


def test_unknown_push_type_without_response_still_maps_buyer_text():
    """WS 外层无 response 字段时，买家消息也不应静默丢弃为 SYSTEM_STATUS。"""
    raw = {
        "message": {
            "type": 77,
            "msg_id": "m-no-response",
            "content": "无 response 字段",
            "from": {"role": "user", "uid": "4216881609"},
            "to": {"role": "mall_cs", "uid": "184046586"},
            "time": 1710000000000,
        },
    }
    pdd = PDDChatMessage(raw)
    assert pdd.user_msg_type == ContextType.TEXT
    assert pdd.content == "无 response 字段"


def test_mall_cs_unknown_type_is_mall_cs():
    raw = {
        "response": "push",
        "message": {
            "type": 99,
            "msg_id": "m-unknown-99",
            "content": "系统扩展",
            "from": {"role": "mall_cs", "uid": "184046586"},
            "to": {"role": "user", "uid": "4216881609"},
            "time": 1710000000000,
        },
    }
    pdd = PDDChatMessage(raw)
    assert pdd.user_msg_type == ContextType.MALL_CS
