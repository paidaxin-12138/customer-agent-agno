"""Turn Abort 运维观测：arun 单线程池队列积压持续告警。"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from core.arun_executor import arun_executor_pending
from utils.logger_loguru import get_logger

_logger = get_logger("TurnAbortWatchdog")


@dataclass
class ArunBacklogState:
    pending_since: Optional[float] = None
    warned: bool = False


def _watch_enabled() -> bool:
    try:
        from config import get_config

        return bool(get_config("chat.turn_abort_arun_backlog_watch_enabled", True))
    except Exception:
        return True


def _arun_backlog_warn_sec() -> float:
    try:
        from config import get_config

        v = float(get_config("chat.turn_abort_arun_backlog_warn_sec", 30) or 30)
        return max(5.0, min(v, 600.0))
    except (TypeError, ValueError):
        return 30.0


def _arun_backlog_poll_sec() -> float:
    try:
        from config import get_config

        v = float(get_config("chat.turn_abort_arun_backlog_poll_sec", 5) or 5)
        return max(1.0, min(v, 60.0))
    except (TypeError, ValueError):
        return 5.0


def evaluate_arun_backlog(
    pending: int,
    state: ArunBacklogState,
    *,
    warn_after_sec: float,
    now: float,
) -> tuple[ArunBacklogState, bool]:
    """返回 (新状态, 本轮是否应打 warning)。"""
    if pending <= 0:
        return ArunBacklogState(), False

    if state.pending_since is None:
        return ArunBacklogState(pending_since=now, warned=False), False

    elapsed = now - state.pending_since
    if not state.warned and elapsed >= warn_after_sec:
        return ArunBacklogState(pending_since=state.pending_since, warned=True), True

    return state, False


async def run_arun_backlog_watch_loop(*, max_ticks: Optional[int] = None) -> None:
    """轮询 arun_executor_pending；积压持续超阈值时打一次 warning。"""
    if not _watch_enabled():
        return

    warn_after = _arun_backlog_warn_sec()
    poll_sec = _arun_backlog_poll_sec()
    state = ArunBacklogState()
    ticks = 0

    while max_ticks is None or ticks < max_ticks:
        ticks += 1
        try:
            pending = arun_executor_pending()
        except Exception as exc:
            _logger.debug("arun backlog 轮询跳过: {}", exc)
            await asyncio.sleep(poll_sec)
            continue

        state, should_warn = evaluate_arun_backlog(
            pending,
            state,
            warn_after_sec=warn_after,
            now=time.monotonic(),
        )
        if should_warn:
            _logger.warning(
                "arun executor 队列积压 pending={} 持续 >= {:.0f}s（可能有孤儿 arun 线程）",
                pending,
                warn_after,
            )
        await asyncio.sleep(poll_sec)
