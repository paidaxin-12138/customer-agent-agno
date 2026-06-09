# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
from Channel.pinduoduo.utils.API.get_messages import (
    parse_mms_conversation_item,
    preview_from_mms_item,
)
from core.mms_session_sync import _should_enqueue_polled_item


def test_parse_mms_conversation_buyer_message():
    item = {
        "from": {"role": "user", "uid": "12345", "nickname": "测试买家"},
        "to": {"role": "mall_cs", "uid": "722406697"},
        "content": "你好",
        "type": 0,
        "ts": "1780627081",
        "msg_id": "1780627081031",
        "context": {"unread": 1},
    }
    parsed = parse_mms_conversation_item(item)
    assert parsed is not None
    assert parsed["buyer_uid"] == "12345"
    assert parsed["sender_role"] == "customer"
    assert parsed["preview"] == "你好"
    assert parsed["unread_hint"] == 1


def test_parse_mms_conversation_mall_cs_last():
    item = {
        "from": {"role": "mall_cs", "uid": "722406697"},
        "to": {"role": "user", "uid": "4456152676"},
        "content": "亲，在的",
        "type": 0,
        "ts": "1780627081",
        "msg_id": "1780627081032",
        "context": {"unread": 0},
    }
    parsed = parse_mms_conversation_item(item)
    assert parsed is not None
    assert parsed["buyer_uid"] == "4456152676"
    assert parsed["sender_role"] == "agent"


def test_preview_video():
    item = {"type": 14, "content": "https://video.example/a.mp4"}
    assert preview_from_mms_item(item) == "[视频]"


def test_should_enqueue_first_unread():
    item = {
        "msg_id": "m1",
        "sender_role": "customer",
        "unread_hint": 1,
    }
    assert _should_enqueue_polled_item(session_id=1, item=item, existed_before=False)
    assert not _should_enqueue_polled_item(session_id=1, item=item, existed_before=False)


def test_should_enqueue_on_new_msg_id():
    item1 = {"msg_id": "m1", "sender_role": "customer", "unread_hint": 0}
    _should_enqueue_polled_item(session_id=2, item=item1, existed_before=True)
    item2 = {"msg_id": "m2", "sender_role": "customer", "unread_hint": 0}
    assert _should_enqueue_polled_item(session_id=2, item=item2, existed_before=False)
