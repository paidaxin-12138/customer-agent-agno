"""Agno 同步 tool 在独立线程池执行，避免阻塞 HTTP 在事件循环线程内直接运行。"""
from __future__ import annotations

import concurrent.futures
import functools
from typing import Any, Callable, Optional, TypeVar

from core.turn_abort import (
    TurnAborted,
    TurnAbortSignal,
    check_turn_abort,
    get_current_turn_abort,
    reset_current_turn_abort,
    set_current_turn_abort,
)
from utils.logger_loguru import get_logger

_log = get_logger("AgnoToolOffload")

F = TypeVar("F", bound=Callable[..., Any])

_TOOL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="agno_tool",
)


def _tool_timeout_sec() -> float:
    try:
        from config import get_config

        v = float(get_config("chat.agno_tool_timeout_sec", 90) or 90)
        return max(5.0, min(v, 300.0))
    except (TypeError, ValueError):
        return 90.0


def _tool_aborted_message(name: str, reason: str = "") -> str:
    detail = reason or "turn abort"
    return f"工具 {name} 已中断（{detail}），请稍后重试或转人工。"


def _run_tool_with_abort(
    fn: Callable[..., Any],
    signal: Optional[TurnAbortSignal],
    args: tuple,
    kwargs: dict,
) -> Any:
    token = set_current_turn_abort(signal) if signal else None
    try:
        check_turn_abort()
        return fn(*args, **kwargs)
    except TurnAborted as exc:
        return _tool_aborted_message(fn.__name__, exc.reason)
    finally:
        if token is not None:
            reset_current_turn_abort(token)


def offload_tool(fn: F) -> F:
    """将 sync tool 整段执行卸载到线程池（供 Agno 在 worker loop 内调用）。"""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        signal = get_current_turn_abort()
        if signal and signal.is_aborted():
            return _tool_aborted_message(fn.__name__, signal.reason())

        timeout = _tool_timeout_sec()
        fut = _TOOL_EXECUTOR.submit(_run_tool_with_abort, fn, signal, args, kwargs)
        try:
            return fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            if signal:
                signal.abort("tool_timeout")
            _log.error("tool {} 超时 ({:.0f}s)", fn.__name__, timeout)
            return f"工具 {fn.__name__} 执行超时，请稍后重试或转人工。"

    return wrapper  # type: ignore[return-value]


def shutdown_tool_executor(*, wait: bool = False) -> None:
    try:
        _TOOL_EXECUTOR.shutdown(wait=wait, cancel_futures=True)
    except Exception:
        pass
