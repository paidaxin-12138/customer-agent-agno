"""计算下一次本地时刻任务执行的秒数。"""
from __future__ import annotations

from datetime import datetime, timedelta


def seconds_until_local(hour: int, minute: int = 0) -> float:
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return max(1.0, (target - now).total_seconds())
