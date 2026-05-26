"""utils.buyer_burst_merge 尾部买家连发合并。"""
from datetime import datetime, timedelta

from utils.buyer_burst_merge import merge_trailing_buyer_burst


def _row(sender: str, content: str, t: datetime) -> dict:
    return {"sender_type": sender, "content": content, "sent_at": t, "created_at": t}


def test_merge_single_char_burst():
    t0 = datetime(2026, 5, 13, 10, 0, 0)
    rows = [
        _row("ai", "hi", t0),
        _row("customer", "你", t0 + timedelta(seconds=1)),
        _row("customer", "好", t0 + timedelta(seconds=2)),
        _row("customer", "啊", t0 + timedelta(seconds=3)),
    ]
    assert merge_trailing_buyer_burst(rows, gap_seconds=45, max_parts=40) == "你好啊"


def test_merge_stops_at_ai():
    t0 = datetime(2026, 5, 13, 10, 0, 0)
    rows = [
        _row("customer", "旧", t0),
        _row("ai", "回", t0 + timedelta(seconds=10)),
        _row("customer", "新", t0 + timedelta(seconds=11)),
    ]
    assert merge_trailing_buyer_burst(rows, gap_seconds=45, max_parts=40) == "新"


def test_merge_stops_on_long_gap():
    t0 = datetime(2026, 5, 13, 10, 0, 0)
    rows = [
        _row("customer", "早", t0),
        _row("customer", "晚", t0 + timedelta(seconds=100)),
    ]
    assert merge_trailing_buyer_burst(rows, gap_seconds=45, max_parts=40) == "晚"
