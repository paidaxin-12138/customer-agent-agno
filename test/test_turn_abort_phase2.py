"""Turn Abort Phase 2/3 TDD。"""
from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from core.turn_abort import (
    TurnAborted,
    TurnAbortRegistry,
    reset_current_turn_abort,
    set_current_turn_abort,
)


def test_abort_watcher_thread_exits_on_success():
    import threading

    from core.turn_abort_loop import run_coroutine_on_private_loop_abortable

    before = sum(
        1 for t in threading.enumerate() if t.name == "turn-abort-watch"
    )

    async def _quick() -> str:
        return "ok"

    for _ in range(5):
        run_coroutine_on_private_loop_abortable(_quick, TurnAbortRegistry().begin_turn("s/u/b"))

    after = sum(
        1 for t in threading.enumerate() if t.name == "turn-abort-watch"
    )
    assert after == before


def test_abort_watcher_thread_exits_on_success():
    import threading

    from core.turn_abort_loop import run_coroutine_on_private_loop_abortable

    reg = TurnAbortRegistry()
    sig = reg.begin_turn("s/u/b")
    before = sum(
        1 for t in threading.enumerate() if t.name == "turn-abort-watch"
    )

    async def _quick() -> str:
        return "ok"

    result = run_coroutine_on_private_loop_abortable(_quick, sig)
    assert result == "ok"

    for _ in range(20):
        after = sum(
            1 for t in threading.enumerate() if t.name == "turn-abort-watch"
        )
        if after == before:
            break
        time.sleep(0.02)
    assert after == before


def test_run_coroutine_on_private_loop_exits_after_abort():
    from core.turn_abort_loop import run_coroutine_on_private_loop_abortable

    reg = TurnAbortRegistry()
    sig = reg.begin_turn("s/u/b")
    entered = threading.Event()
    finished = threading.Event()

    async def _slow() -> str:
        entered.set()
        await asyncio.sleep(30)
        return "late"

    def _runner() -> None:
        try:
            run_coroutine_on_private_loop_abortable(_slow, sig)
        except TurnAborted:
            pass
        except asyncio.CancelledError:
            pass
        finally:
            finished.set()

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    assert entered.wait(3)
    sig.abort("test_abort")
    assert finished.wait(3)
    assert sig.is_aborted()


def test_offload_tool_returns_aborted_message_when_signal_aborted():
    from utils.agno_tool_offload import offload_tool

    reg = TurnAbortRegistry()
    sig = reg.begin_turn("s/u/b")
    sig.abort("superseded")
    tok = set_current_turn_abort(sig)

    @offload_tool
    def _sample_tool() -> str:
        return "should not run"

    try:
        result = _sample_tool()
    finally:
        reset_current_turn_abort(tok)

    assert "中断" in result
    assert "superseded" in result


def test_offload_tool_aborts_signal_on_timeout():
    from utils import agno_tool_offload as mod

    reg = TurnAbortRegistry()
    sig = reg.begin_turn("s/u/b")
    tok = set_current_turn_abort(sig)

    @mod.offload_tool
    def _slow_tool() -> str:
        time.sleep(30)
        return "late"

    try:
        with patch.object(mod, "_tool_timeout_sec", return_value=0.05):
            result = _slow_tool()
    finally:
        reset_current_turn_abort(tok)

    assert "超时" in result
    assert sig.is_aborted()
    assert sig.reason() == "tool_timeout"


def test_fetch_mall_products_stops_pagination_on_abort():
    from Agent.CustomerAgent.tools.get_product_list import _fetch_mall_products_paginated

    reg = TurnAbortRegistry()
    sig = reg.begin_turn("s/u/b")
    tok = set_current_turn_abort(sig)

    pm = MagicMock()
    pages: list[int] = []

    def _list_page(*, page: int, size: int):
        pages.append(page)
        if page == 1:
            sig.abort("superseded_by_new_inbound")
        return {
            "success": True,
            "products": [{"goods_id": f"g{page}"}],
            "total": 500,
        }

    pm.get_product_list.side_effect = _list_page

    try:
        with patch(
            "scripts.sync_goods_to_kb._should_fetch_next_goods_page",
            return_value=True,
        ):
            with pytest.raises(TurnAborted):
                _fetch_mall_products_paginated(pm, max_pages=5)
    finally:
        reset_current_turn_abort(tok)

    assert pages == [1]
