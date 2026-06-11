"""Turn Abort 运维：arun 队列积压告警 TDD。"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from core.turn_abort_watchdog import (
    ArunBacklogState,
    evaluate_arun_backlog,
    run_arun_backlog_watch_loop,
)


def test_no_warn_when_pending_zero():
    state = ArunBacklogState()
    state, warn = evaluate_arun_backlog(0, state, warn_after_sec=10.0, now=100.0)
    assert warn is False
    assert state.pending_since is None


def test_no_warn_before_threshold():
    state = ArunBacklogState()
    state, _ = evaluate_arun_backlog(1, state, warn_after_sec=10.0, now=100.0)
    state, warn = evaluate_arun_backlog(1, state, warn_after_sec=10.0, now=105.0)
    assert warn is False


def test_warns_once_after_threshold():
    state = ArunBacklogState()
    state, _ = evaluate_arun_backlog(1, state, warn_after_sec=10.0, now=100.0)
    state, warn = evaluate_arun_backlog(1, state, warn_after_sec=10.0, now=111.0)
    assert warn is True
    state, warn2 = evaluate_arun_backlog(1, state, warn_after_sec=10.0, now=120.0)
    assert warn2 is False


def test_resets_when_pending_clears():
    state = ArunBacklogState()
    state, _ = evaluate_arun_backlog(1, state, warn_after_sec=10.0, now=100.0)
    state, _ = evaluate_arun_backlog(1, state, warn_after_sec=10.0, now=115.0)
    state, warn = evaluate_arun_backlog(0, state, warn_after_sec=10.0, now=120.0)
    assert warn is False
    assert state.pending_since is None
    state, warn2 = evaluate_arun_backlog(1, state, warn_after_sec=10.0, now=125.0)
    assert warn2 is False
    state, warn3 = evaluate_arun_backlog(1, state, warn_after_sec=10.0, now=136.0)
    assert warn3 is True


@pytest.mark.asyncio
async def test_watch_loop_logs_warning():
    clock = {"t": 100.0}

    def _mono():
        return clock["t"]

    async def _fake_sleep(sec: float) -> None:
        clock["t"] += sec

    with patch(
        "core.turn_abort_watchdog._arun_backlog_poll_sec", return_value=0.01
    ), patch(
        "core.turn_abort_watchdog._arun_backlog_warn_sec", return_value=0.02
    ), patch(
        "core.turn_abort_watchdog._watch_enabled", return_value=True
    ), patch(
        "core.turn_abort_watchdog.arun_executor_pending", return_value=1
    ), patch("core.turn_abort_watchdog.time.monotonic", side_effect=_mono), patch(
        "core.turn_abort_watchdog.asyncio.sleep", side_effect=_fake_sleep
    ), patch("core.turn_abort_watchdog._logger") as log_mock:
        await run_arun_backlog_watch_loop(max_ticks=5)

    assert any(
        "arun executor 队列积压" in str(c)
        for c in log_mock.warning.call_args_list
    )
