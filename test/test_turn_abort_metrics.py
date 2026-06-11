"""Turn Abort Phase 4：/metrics 可观测性 TDD。"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from core.app_metrics import (
    get_metrics_payload,
    get_turn_abort_metrics,
    record_turn_abort,
    record_turn_stale_dropped,
)
from core.turn_abort import TurnAbortRegistry

_METRICS_PATCHES = (
    patch("core.app_metrics.get_cache_sizes", return_value={}),
    patch("core.app_metrics.get_queue_depth_snapshot", return_value=0),
    patch(
        "core.app_metrics.get_handler_chain_metrics",
        return_value={"ok": True, "missing": []},
    ),
)


def test_record_turn_abort_counts_by_reason():
    before = get_turn_abort_metrics()["by_reason"].get("arun_timeout", 0)
    record_turn_abort("arun_timeout")
    record_turn_abort("arun_timeout")
    record_turn_abort("tool_timeout")

    metrics = get_turn_abort_metrics()
    assert metrics["by_reason"]["arun_timeout"] >= before + 2
    assert metrics["by_reason"]["tool_timeout"] >= 1


def test_record_turn_stale_dropped():
    before = get_turn_abort_metrics()["stale_dropped_total"]
    record_turn_stale_dropped()
    assert get_turn_abort_metrics()["stale_dropped_total"] >= before + 1


def test_metrics_payload_includes_turn_abort():
    record_turn_abort("superseded_by_new_inbound")
    with _METRICS_PATCHES[0], _METRICS_PATCHES[1], _METRICS_PATCHES[2]:
        payload = get_metrics_payload()
    assert "turn_abort" in payload
    ta = payload["turn_abort"]
    assert "by_reason" in ta
    assert "stale_dropped_total" in ta
    assert "active_sessions" in ta
    assert "arun_executor_pending" in ta


def test_signal_abort_records_metric():
    reg = TurnAbortRegistry()
    sig = reg.begin_turn("s/u/b")
    with patch("core.app_metrics.record_turn_abort") as mock_record:
        sig.abort("manual_test")
    mock_record.assert_called_once_with("manual_test")


def test_registry_stale_dropped_records_metric():
    reg = TurnAbortRegistry()
    with patch("core.app_metrics.record_turn_stale_dropped") as mock_record:
        reg.record_stale_dropped()
    mock_record.assert_called_once()


def test_begin_turn_supersede_records_abort_metric():
    reg = TurnAbortRegistry()
    reg.begin_turn("s/u/b")
    with patch("core.app_metrics.record_turn_abort") as mock_record:
        reg.begin_turn("s/u/b")
    mock_record.assert_called_with("superseded_by_new_inbound")


def test_turn_abort_registry_snapshot_stats():
    reg = TurnAbortRegistry()
    reg.begin_turn("a/u/b")
    stats = reg.snapshot_stats()
    assert stats["active_sessions"] == 1
    assert stats["aborted_total"] == 0
    assert stats["stale_dropped_total"] == 0


@pytest.mark.asyncio
async def test_metrics_handler_includes_turn_abort():
    from aiohttp.test_utils import make_mocked_request

    from core.health_server import _metrics_handler

    record_turn_abort("arun_timeout")
    with _METRICS_PATCHES[0], _METRICS_PATCHES[1], _METRICS_PATCHES[2]:
        resp = await _metrics_handler(make_mocked_request("GET", "/metrics"))
    assert resp.status == 200
    data = json.loads(resp.text)
    assert "turn_abort" in data
    assert "by_reason" in data["turn_abort"]
