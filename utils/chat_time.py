"""聊天消息时间：统一按 Asia/Shanghai 写入与理解，避免 UTC naive 显示错位。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

_SH = ZoneInfo("Asia/Shanghai")


def shanghai_naive_now() -> datetime:
    """当前上海墙钟时间的 naive datetime（与 SQLite 存 datetime 常见用法一致）。"""
    return datetime.now(_SH).replace(tzinfo=None)


def naive_shanghai_from_unix_ts(ts: Optional[float]) -> datetime:
    """Unix 秒时间戳 → 上海墙钟 naive datetime。"""
    if ts is None:
        return shanghai_naive_now()
    try:
        sec = float(ts)
        if sec > 1e12:
            sec /= 1000.0
        return datetime.fromtimestamp(sec, tz=timezone.utc).astimezone(_SH).replace(tzinfo=None)
    except (ValueError, OSError, TypeError, OverflowError):
        return shanghai_naive_now()


def format_chat_timestamp(t: Any) -> str:
    """界面气泡旁展示：月-日 时:分（按上海）。"""
    if t is None:
        return ""
    if isinstance(t, datetime):
        if t.tzinfo is not None:
            local = t.astimezone(_SH)
        else:
            local = t.replace(tzinfo=_SH)
        return local.strftime("%m-%d %H:%M")
    s = str(t).strip()
    return s[:16] if len(s) > 16 else s
