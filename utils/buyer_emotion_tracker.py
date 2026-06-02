"""按会话统计买家情绪波动预警次数（内存计数，进程重启清零）。"""
from __future__ import annotations

from threading import Lock
from typing import Dict

_lock = Lock()
_counts: Dict[str, int] = {}


def record_emotion_alert(session_key: str) -> int:
    """记录一次情绪波动，返回当前累计次数。"""
    key = (session_key or "").strip()
    if not key:
        return 1
    with _lock:
        n = _counts.get(key, 0) + 1
        _counts[key] = n
        return n


def get_emotion_alert_count(session_key: str) -> int:
    key = (session_key or "").strip()
    if not key:
        return 0
    with _lock:
        return _counts.get(key, 0)


def reset_emotion_alerts(session_key: str) -> None:
    key = (session_key or "").strip()
    if not key:
        return
    with _lock:
        _counts.pop(key, None)
