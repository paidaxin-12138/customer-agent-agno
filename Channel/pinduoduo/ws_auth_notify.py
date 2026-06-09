# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""WebSocket AUTH 结果通知（成功后再提示 UI；连续失败则停止重连）。"""
from __future__ import annotations

from typing import Callable, Dict, Optional

from utils.logger_loguru import get_logger

_log = get_logger("WSAuthNotify")

AUTH_FAIL_FATAL_THRESHOLD = 3

_success_callbacks: Dict[str, Callable[[], None]] = {}
_stop_callbacks: Dict[str, Callable[[], None]] = {}
_fail_counts: Dict[str, int] = {}
_fatal_messages: Dict[str, str] = {}


def register_auth_success_callback(key: str, callback: Callable[[], None]) -> None:
    _success_callbacks[key] = callback


def register_auth_stop_callback(key: str, callback: Callable[[], None]) -> None:
    _stop_callbacks[key] = callback


def clear_auth_success_callback(key: str) -> None:
    _success_callbacks.pop(key, None)


def clear_auth_stop_callback(key: str) -> None:
    _stop_callbacks.pop(key, None)


def clear_auth_callbacks(key: str) -> None:
    clear_auth_success_callback(key)
    clear_auth_stop_callback(key)
    _fail_counts.pop(key, None)
    _fatal_messages.pop(key, None)


def notify_auth_success(key: str) -> None:
    _fail_counts.pop(key, None)
    _fatal_messages.pop(key, None)
    cb = _success_callbacks.pop(key, None)
    if cb is None:
        return
    try:
        cb()
    except Exception as exc:
        _log.warning("auth success callback failed key={}: {}", key, exc)


def record_auth_failure(
    key: str,
    *,
    username: str = "",
    threshold: int = AUTH_FAIL_FATAL_THRESHOLD,
) -> bool:
    """
    记录 AUTH 失败。连续达到 threshold 次则触发 stop 回调并写入 fatal 消息。
    返回是否已达致命阈值。
    """
    count = _fail_counts.get(key, 0) + 1
    _fail_counts[key] = count
    if count < threshold:
        return False

    _fail_counts[key] = 0
    label = username or key
    _fatal_messages[key] = (
        f"账号「{label}」WebSocket 认证失败（可能 Cookie 已过期），"
        "请到「用户管理」重新登录后再点「开始回复」。"
    )
    stop_cb = _stop_callbacks.get(key)
    if stop_cb is not None:
        try:
            stop_cb()
        except Exception as exc:
            _log.warning("auth stop callback failed key={}: {}", key, exc)
    return True


def pop_fatal_auth_message(key: str) -> Optional[str]:
    return _fatal_messages.pop(key, None)
