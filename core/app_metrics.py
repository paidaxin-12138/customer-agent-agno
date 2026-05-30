"""进程内轻量指标（供 /metrics 与健康检查旁路观测）。"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict

_lock = threading.Lock()
_messages_processed = 0
_messages_failed = 0
_started_at = time.time()


def record_message_processed() -> None:
    global _messages_processed
    with _lock:
        _messages_processed += 1


def record_message_failed() -> None:
    global _messages_failed
    with _lock:
        _messages_failed += 1


def get_queue_depth_snapshot() -> int:
    try:
        from Message.core.queue import queue_manager

        stats = queue_manager.list_queues()
        return sum(int(s.current_size) for s in stats.values())
    except Exception:
        return 0


def get_metrics_payload() -> Dict[str, Any]:
    with _lock:
        processed = _messages_processed
        failed = _messages_failed
    uptime = max(0.0, time.time() - _started_at)
    return {
        "messages_processed": processed,
        "messages_failed": failed,
        "queue_depth_approx": get_queue_depth_snapshot(),
        "uptime_seconds": round(uptime, 1),
    }
