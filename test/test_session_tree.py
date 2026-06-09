# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
from ui.chat.session_tree import (
    format_session_tree_label,
    session_matches_filter,
    session_sort_key,
)


def test_session_sort_key_prefers_unread():
    a = {"unread_count": 0, "last_message_time": None, "updated_at": None}
    b = {"unread_count": 2, "last_message_time": None, "updated_at": None}
    assert session_sort_key(b) > session_sort_key(a)


def test_session_matches_filter():
    s = {"buyer_nickname": "小明", "last_message": "你好", "buyer_uid": "123"}
    assert session_matches_filter(s, "小明")
    assert not session_matches_filter(s, "zzz")


def test_format_session_tree_label_includes_nick():
    label = format_session_tree_label(
        {
            "buyer_nickname": "买家A",
            "last_message": "在吗",
            "unread_count": 1,
            "last_message_time": None,
        }
    )
    assert "买家A" in label
    assert "在吗" in label
