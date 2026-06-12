# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""未回复买家消息合并。"""
from utils.unreplied_buyer_messages import (
    collect_unreplied_buyer_messages,
    merge_unreplied_parts,
)


def test_collect_after_last_reply():
    rows = [
        {"sender_type": "customer", "content": "第一个问题"},
        {"sender_type": "ai", "content": "已回答"},
        {"sender_type": "customer", "content": "第二个"},
        {"sender_type": "customer", "content": "第三个"},
    ]
    parts = collect_unreplied_buyer_messages(rows, max_scan=5, max_parts=3)
    assert parts == ["第二个", "第三个"]


def test_platform_civility_not_counted_as_reply():
    rows = [
        {"sender_type": "customer", "content": "脏话"},
        {"sender_type": "human", "content": "请文明用语"},
        {"sender_type": "customer", "content": "真正的问题"},
    ]
    parts = collect_unreplied_buyer_messages(rows, max_scan=5, max_parts=3)
    assert "真正的问题" in parts
    assert "脏话" in parts


def test_agent_reply_from_mms_sync_counts_as_effective():
    rows = [
        {"sender_type": "customer", "content": "别人家比你便宜"},
        {"sender_type": "agent", "content": "亲亲，咱们这款灯主打速干…"},
        {"sender_type": "customer", "content": "？"},
    ]
    parts = collect_unreplied_buyer_messages(rows, max_scan=5, max_parts=3)
    assert parts == ["？"]


def test_merge_prompt():
    text = merge_unreplied_parts(["A", "B", "C"])
    assert "用户先问：A" in text
    assert "然后问：B" in text
    assert "请一并回答" in text


def test_merge_truncates_earlier_messages():
    long_a = "A" * 1200
    text = merge_unreplied_parts([long_a, "短问题B", "短问题C"], max_chars=500)
    assert "短问题" in text
    assert long_a not in text
