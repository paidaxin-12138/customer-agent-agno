"""Turn abort 与私有 event loop 协作退出（Phase 2）。"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Awaitable, Callable, Optional, TypeVar

from core.turn_abort import TurnAborted, TurnAbortSignal

T = TypeVar("T")


def _loop_stop_grace_ms() -> float:
    try:
        from config import get_config

        v = float(get_config("chat.turn_abort_loop_stop_grace_ms", 500) or 500)
        return max(50.0, min(v, 5000.0))
    except (TypeError, ValueError):
        return 500.0


def _wait_aborted_loop_grace(
    loop: asyncio.AbstractEventLoop,
    signal: Optional[TurnAbortSignal],
    task: Optional[asyncio.Task],
) -> None:
    """abort 后短暂等待 loop/task 自行收尾，再强制 cancel 剩余 task。"""
    if signal is None or not signal.is_aborted() or task is None:
        return
    grace_sec = _loop_stop_grace_ms() / 1000.0
    deadline = time.monotonic() + grace_sec
    while time.monotonic() < deadline and not task.done():
        time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))


def wire_abort_to_loop(
    signal: TurnAbortSignal,
    loop: asyncio.AbstractEventLoop,
    task: asyncio.Task,
    done: threading.Event,
) -> threading.Thread:
    """abort 时在 loop 线程 cancel task 并 stop loop；正常完成时由 done 唤醒退出。"""

    def _watch() -> None:
        while True:
            if done.wait(timeout=0.05):
                return
            if task.done():
                return
            if not signal._event.is_set():
                continue

            def _stop() -> None:
                if not task.done():
                    task.cancel()
                loop.stop()

            try:
                loop.call_soon_threadsafe(_stop)
            except RuntimeError:
                pass
            return

    watcher = threading.Thread(
        target=_watch, daemon=True, name="turn-abort-watch"
    )
    watcher.start()
    return watcher


def run_coroutine_on_private_loop_abortable(
    coro_factory: Callable[[], Awaitable[T]],
    signal: Optional[TurnAbortSignal],
) -> T:
    """在独立 loop 中运行 coroutine；signal abort 时 cancel task 并尽快退出。"""
    loop = asyncio.new_event_loop()
    task: Optional[asyncio.Task] = None
    watcher_done = threading.Event()
    watcher: Optional[threading.Thread] = None
    try:
        asyncio.set_event_loop(loop)
        if signal and signal.is_aborted():
            raise TurnAborted(signal.reason(), signal.turn_id)

        task = loop.create_task(coro_factory())
        if signal is not None:
            watcher = wire_abort_to_loop(signal, loop, task, watcher_done)

        try:
            return loop.run_until_complete(task)
        except asyncio.CancelledError:
            if signal and signal.is_aborted():
                raise TurnAborted(signal.reason(), signal.turn_id) from None
            raise
        except RuntimeError as exc:
            if signal and signal.is_aborted() and "Event loop stopped" in str(exc):
                raise TurnAborted(signal.reason(), signal.turn_id) from None
            raise
    finally:
        watcher_done.set()
        if watcher is not None and watcher.is_alive():
            watcher.join(timeout=0.25)
        _finalize_private_loop(loop, signal, task)
        loop.close()
        asyncio.set_event_loop(None)


def _finalize_private_loop(
    loop: asyncio.AbstractEventLoop,
    signal: Optional[TurnAbortSignal],
    task: Optional[asyncio.Task],
) -> None:
    try:
        _wait_aborted_loop_grace(loop, signal, task)
        pending = asyncio.all_tasks(loop)
        for t in pending:
            if not t.done():
                t.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    except Exception:
        pass
    try:
        loop.run_until_complete(loop.shutdown_asyncgens())
    except Exception:
        pass
