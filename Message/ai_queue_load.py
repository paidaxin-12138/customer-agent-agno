"""
AI 回复链路负载：活跃任务计数 + 成功耗时滑动窗口（排队降级用）。
"""
from __future__ import annotations

import asyncio
import statistics
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Deque, Optional

from config import get_config

_tracker: Optional["AIQueueLoadTracker"] = None


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


class AIQueueLoadTracker:
    """进程内单例：active_ai_tasks + P95 预估（见 docs/AI回复兜底设计说明-v2.md）。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active = 0
        self._window: Deque[float] = deque(maxlen=100)

    @property
    def active_tasks(self) -> int:
        return self._active

    def record_success_duration(self, duration_sec: float) -> None:
        d = float(duration_sec)
        if d <= 0:
            return
        self._window.append(d)

    def effective_duration_sec(self) -> float:
        cap = _cfg_float("chat.queue_p95_cap_sec", 30.0, 5.0, 120.0)
        prior = _cfg_float("chat.queue_prior_duration_sec", 8.0, 1.0, 60.0)
        min_samples = _cfg_int("chat.queue_stats_min_samples", 10, 1, 100)
        recent_n = _cfg_int("chat.queue_stats_recent_size", 20, 5, 100)

        if len(self._window) < min_samples:
            return min(prior, cap)

        vals = list(self._window)
        raw_p95 = _percentile(sorted(vals), 95.0)
        recent = vals[-recent_n:] if len(vals) >= recent_n else vals
        recent_med = statistics.median(recent) if recent else prior
        return min(raw_p95, recent_med * 2.0, cap)

    def estimated_wait_sec(self) -> float:
        return (self._active + 1) * self.effective_duration_sec()

    def should_queue_degrade(self) -> bool:
        if not bool(get_config("chat.queue_degrade_enabled", True)):
            return False
        threshold = _cfg_float("chat.queue_degrade_threshold_sec", 120.0, 30.0, 600.0)
        return self.estimated_wait_sec() > threshold

    @asynccontextmanager
    async def ai_inflight(self):
        async with self._lock:
            self._active += 1
        try:
            yield
        finally:
            async with self._lock:
                self._active = max(0, self._active - 1)


def get_ai_queue_tracker() -> AIQueueLoadTracker:
    global _tracker
    if _tracker is None:
        _tracker = AIQueueLoadTracker()
    return _tracker


def _cfg_float(key: str, default: float, lo: float, hi: float) -> float:
    try:
        v = float(get_config(key, default))
        return max(lo, min(v, hi))
    except (TypeError, ValueError):
        return default


def _cfg_int(key: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(get_config(key, default))
        return max(lo, min(v, hi))
    except (TypeError, ValueError):
        return default
