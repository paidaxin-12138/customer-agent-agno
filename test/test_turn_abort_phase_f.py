"""Turn Abort Phase F：配置对齐、loop grace、executor shutdown。"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from core.turn_abort import TurnAbortRegistry


def test_chat_config_includes_arun_and_tool_timeout():
    from config_schema import ChatConfig

    cfg = ChatConfig(llm_arun_timeout_sec=120, agno_tool_timeout_sec=90)
    assert cfg.llm_arun_timeout_sec == 120
    assert cfg.agno_tool_timeout_sec == 90


def test_config_example_includes_arun_and_tool_timeout():
    from pathlib import Path

    text = Path("config.json.example").read_text(encoding="utf-8")
    assert "llm_arun_timeout_sec" in text
    assert "agno_tool_timeout_sec" in text


def test_wait_aborted_loop_grace_returns_immediately_when_task_done():
    from core.turn_abort_loop import _wait_aborted_loop_grace

    reg = TurnAbortRegistry()
    sig = reg.begin_turn("s/u/b")
    sig.abort("test")
    loop = asyncio.new_event_loop()
    try:

        async def _fast() -> int:
            return 1

        task = loop.create_task(_fast())
        loop.run_until_complete(task)
        sleeps: list[float] = []
        with patch("core.turn_abort_loop.time.sleep", side_effect=lambda s: sleeps.append(s)):
            with patch("core.turn_abort_loop._loop_stop_grace_ms", return_value=500):
                _wait_aborted_loop_grace(loop, sig, task)
        assert sleeps == []
    finally:
        loop.close()


def test_wait_aborted_loop_grace_waits_until_deadline_when_task_pending():
    from core.turn_abort_loop import _wait_aborted_loop_grace

    reg = TurnAbortRegistry()
    sig = reg.begin_turn("s/u/b")
    sig.abort("test")
    loop = asyncio.new_event_loop()
    try:
        task = MagicMock()
        task.done.return_value = False
        real_sleep = time.sleep
        slept: list[float] = []

        def _track_sleep(sec: float) -> None:
            slept.append(sec)
            real_sleep(min(sec, 0.05))

        with patch("core.turn_abort_loop.time.sleep", side_effect=_track_sleep):
            with patch("core.turn_abort_loop._loop_stop_grace_ms", return_value=80):
                t0 = time.monotonic()
                _wait_aborted_loop_grace(loop, sig, task)
                elapsed = time.monotonic() - t0
        assert elapsed >= 0.06
        assert sum(slept) >= 0.06
    finally:
        loop.close()


def test_shutdown_application_shuts_down_executors(monkeypatch):
    from core import app_shutdown

    app_shutdown._done = False
    arun_shutdown = MagicMock()
    tool_shutdown = MagicMock()
    monkeypatch.setattr("core.arun_executor.shutdown_arun_executor", arun_shutdown)
    monkeypatch.setattr("utils.agno_tool_offload.shutdown_tool_executor", tool_shutdown)
    monkeypatch.setattr(
        "ui.auto_reply_ui.auto_reply_manager.stop_all",
        lambda: None,
    )
    monkeypatch.setattr(
        "Message.core.consumer.message_consumer_manager",
        type(
            "_Mgr",
            (),
            {
                "list_consumers": staticmethod(lambda: []),
                "get_consumer": staticmethod(lambda _n: None),
                "detach_all": staticmethod(lambda: None),
            },
        )(),
    )

    def _run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    monkeypatch.setattr("core.app_shutdown.asyncio.run", _run)
    monkeypatch.setattr("core.pdd_channel_registry.iter_registered_channels", lambda: [])
    monkeypatch.setattr(
        "Message.handlers.ai_reply_watchdog.cancel_all_watchdogs",
        lambda: asyncio.sleep(0),
    )
    monkeypatch.setattr(
        "core.production_services.stop_production_background_services",
        lambda: None,
    )
    monkeypatch.setattr(
        "database.chat_message_buffer.flush_chat_message_buffer",
        lambda: 0,
    )

    app_shutdown.shutdown_application()
    arun_shutdown.assert_called_once_with(wait=False)
    tool_shutdown.assert_called_once_with(wait=False)
