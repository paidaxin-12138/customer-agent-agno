"""聊天时间格式化。"""
from datetime import datetime

from utils.chat_time import format_chat_display_relative, format_chat_iso


def test_format_chat_iso():
    dt = datetime(2026, 5, 30, 14, 30, 5)
    assert format_chat_iso(dt) == "2026-05-30 14:30:05"


def test_format_chat_display_relative_today():
    from utils.chat_time import shanghai_naive_now

    now = shanghai_naive_now()
    s = format_chat_display_relative(now)
    assert s.startswith("今天 ")
