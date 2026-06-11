"""Agent arun 专用单线程池（避免 app_metrics 反向 import CustomerAgent）。"""
from __future__ import annotations

import concurrent.futures
import threading

_pending_lock = threading.Lock()
_pending_count = 0


class _TrackingThreadPoolExecutor(concurrent.futures.ThreadPoolExecutor):
    """跟踪队列深度，避免依赖 CPython 私有 _work_queue。"""

    def submit(self, fn, /, *args, **kwargs):
        global _pending_count
        with _pending_lock:
            _pending_count += 1
        try:
            return super().submit(self._run_tracked, fn, *args, **kwargs)
        except Exception:
            with _pending_lock:
                _pending_count = max(0, _pending_count - 1)
            raise

    def _run_tracked(self, fn, *args, **kwargs):
        global _pending_count
        try:
            return fn(*args, **kwargs)
        finally:
            with _pending_lock:
                _pending_count = max(0, _pending_count - 1)


ARUN_EXECUTOR = _TrackingThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="agent_arun",
)


def arun_executor_pending() -> int:
    with _pending_lock:
        return int(_pending_count)


def shutdown_arun_executor(*, wait: bool = False) -> None:
    try:
        ARUN_EXECUTOR.shutdown(wait=wait, cancel_futures=True)
    except Exception:
        pass
