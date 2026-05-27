"""时间工具：上海墙钟与展示格式。"""
from datetime import datetime

from utils.chat_time import format_display_datetime, now_for_db, shanghai_naive_now


def test_now_for_db_is_shanghai_wall():
    n = now_for_db()
    sh = shanghai_naive_now()
    assert abs((n - sh).total_seconds()) < 2


def test_format_display_datetime_naive():
    t = datetime(2026, 5, 26, 16, 28, 1)
    assert format_display_datetime(t) == "2026-05-26 16:28:01"
