# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""进程内轻量指标（供 /metrics 与健康检查旁路观测）。"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict

from utils.logger_loguru import get_logger

_log = get_logger("AppMetrics")

_lock = threading.Lock()
_messages_processed = 0
_messages_failed = 0
_ws_reconnects = 0
_cookie_refresh_failures = 0
_queue_enqueue_dropped = 0
_queue_dead_letters = 0
_queue_force_dropped = 0
_turn_abort_by_reason: Dict[str, int] = {}
_turn_stale_dropped = 0
_started_at = time.time()


def record_message_processed() -> None:
    global _messages_processed
    with _lock:
        _messages_processed += 1


def record_message_failed() -> None:
    global _messages_failed
    with _lock:
        _messages_failed += 1


def record_ws_reconnect() -> None:
    global _ws_reconnects
    with _lock:
        _ws_reconnects += 1


def record_cookie_refresh_failure() -> None:
    global _cookie_refresh_failures
    with _lock:
        _cookie_refresh_failures += 1


def record_queue_enqueue_dropped(queue_name: str = "") -> None:
    global _queue_enqueue_dropped
    with _lock:
        _queue_enqueue_dropped += 1
    _log.warning("队列入队失败已记录 queue={}", queue_name or "?")


def record_queue_dead_letter(queue_name: str = "") -> None:
    global _queue_dead_letters
    with _lock:
        _queue_dead_letters += 1
    _log.warning("dead-letter 已记录 queue={}", queue_name or "?")


def record_queue_force_dropped(queue_name: str = "") -> None:
    global _queue_force_dropped
    with _lock:
        _queue_force_dropped += 1
    _log.warning("force_enqueue 丢弃已记录 queue={}", queue_name or "?")


def record_turn_abort(reason: str = "aborted") -> None:
    """Turn 协作取消计数（按 reason 分桶）。"""
    key = str(reason or "aborted").strip() or "aborted"
    with _lock:
        _turn_abort_by_reason[key] = _turn_abort_by_reason.get(key, 0) + 1


def record_turn_stale_dropped() -> None:
    global _turn_stale_dropped
    with _lock:
        _turn_stale_dropped += 1


def get_turn_abort_metrics() -> Dict[str, Any]:
    with _lock:
        by_reason = dict(_turn_abort_by_reason)
        stale = _turn_stale_dropped
    active_sessions = 0
    registry_aborted = 0
    registry_stale = 0
    try:
        from core.turn_abort import turn_abort_registry

        snap = turn_abort_registry.snapshot_stats()
        active_sessions = int(snap.get("active_sessions", 0))
        registry_aborted = int(snap.get("aborted_total", 0))
        registry_stale = int(snap.get("stale_dropped_total", 0))
    except Exception as exc:
        _log.debug("turn_abort registry 快照失败: {}", exc)

    arun_pending = -1
    try:
        from core.arun_executor import arun_executor_pending

        arun_pending = arun_executor_pending()
    except Exception as exc:
        _log.debug("arun executor 队列深度读取失败: {}", exc)

    return {
        "by_reason": by_reason,
        "stale_dropped_total": stale,
        "registry_aborted_total": registry_aborted,
        "registry_stale_dropped_total": registry_stale,
        "active_sessions": active_sessions,
        "arun_executor_pending": arun_pending,
    }


def get_queue_depth_snapshot() -> int:
    try:
        from Message.core.queue import queue_manager

        stats = queue_manager.list_queues()
        return sum(int(s.current_size) for s in stats.values())
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        _log.debug("队列深度快照失败: {}", exc)
        return 0


def get_handler_chain_metrics() -> Dict[str, Any]:
    try:
        from Message.handler_chain_factory import get_handler_chain_status

        return get_handler_chain_status()
    except (ImportError, AttributeError, RuntimeError) as exc:
        _log.debug("处理器链指标不可用: {}", exc)
        return {"ok": False, "missing": [], "errors": {}, "audited": False}


def get_cache_sizes() -> Dict[str, int]:
    """进程内缓存规模快照（Hub / 图片 LRU / 买家锁）。"""
    sizes: Dict[str, int] = {}
    try:
        from ui.conversation_hub import get_conversation_hub

        hub = get_conversation_hub()
        with hub._lock:
            sizes["hub_accounts"] = len(hub._by_account)
            sizes["hub_buyers_total"] = sum(len(acc) for acc in hub._by_account.values())
    except (ImportError, AttributeError, RuntimeError) as exc:
        _log.debug("Hub 缓存规模读取失败: {}", exc)
        sizes["hub_accounts"] = -1
        sizes["hub_buyers_total"] = -1

    try:
        from utils.chat_image_cache import get_chat_image_cache

        cache = get_chat_image_cache()
        with cache._lock:
            sizes["image_cache_count"] = len(cache._cache)
            sizes["image_cache_loading"] = len(cache._loading)
    except (ImportError, AttributeError, RuntimeError) as exc:
        _log.debug("图片缓存规模读取失败: {}", exc)
        sizes["image_cache_count"] = -1
        sizes["image_cache_loading"] = -1

    try:
        from Message.core.consumer import message_consumer_manager

        lock_total = 0
        for consumer in message_consumer_manager._consumers.values():
            lock_total += len(consumer._buyer_locks._locks)
        sizes["buyer_lock_registry"] = lock_total
    except (ImportError, AttributeError, KeyError) as exc:
        _log.debug("买家锁表规模读取失败: {}", exc)
        sizes["buyer_lock_registry"] = -1

    return sizes


def get_metrics_payload() -> Dict[str, Any]:
    turn_abort = get_turn_abort_metrics()
    with _lock:
        processed = _messages_processed
        failed = _messages_failed
        ws_reconnects = _ws_reconnects
        cookie_refresh_failures = _cookie_refresh_failures
        queue_enqueue_dropped = _queue_enqueue_dropped
        queue_dead_letters = _queue_dead_letters
        queue_force_dropped = _queue_force_dropped
    uptime = max(0.0, time.time() - _started_at)
    handler_chain = get_handler_chain_metrics()
    return {
        "messages_processed": processed,
        "messages_failed": failed,
        "queue_depth_approx": get_queue_depth_snapshot(),
        "ws_reconnects": ws_reconnects,
        "cookie_refresh_failures": cookie_refresh_failures,
        "queue_enqueue_dropped": queue_enqueue_dropped,
        "queue_dead_letters": queue_dead_letters,
        "queue_force_dropped": queue_force_dropped,
        "turn_abort": turn_abort,
        "handler_chain_ok": handler_chain.get("ok", False),
        "handler_chain_missing": handler_chain.get("missing", []),
        "uptime_seconds": round(uptime, 1),
        "cache_sizes": get_cache_sizes(),
    }
