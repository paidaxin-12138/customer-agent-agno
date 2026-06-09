# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""WebSocket 重连循环（从 pdd_chnnel 抽离，便于单测）。"""
from __future__ import annotations

import asyncio
import random
from typing import Awaitable, Callable, Dict, Optional

from Channel.pinduoduo.ws_config import ReconnectConfig, connection_key
from Channel.pinduoduo.ws_errors import WsCredentialError
from core.connection_status import ConnectionState, ConnectionStatusManager
from utils.logger_loguru import get_logger

_logger = get_logger("WSReconnect")

ConnectAttemptFn = Callable[
    [str, str, str, Callable, Callable],
    Awaitable[None],
]


async def interruptible_sleep(
    delay: float,
    *,
    connection_key: str,
    shop_id: str,
    user_id: str,
    username: str,
    stop_events: Dict[str, asyncio.Event],
    status_manager: ConnectionStatusManager,
    logger=None,
) -> bool:
    """可中断等待；返回 False 表示应停止重连。"""
    log = logger or _logger
    stop_ev = stop_events.get(connection_key)
    steps = max(1, int(delay * 10))
    for _ in range(steps):
        if stop_ev and stop_ev.is_set():
            log.info(f"重连等待被停止信号中断: {shop_id}-{username}")
            status_manager.update_status(
                shop_id, user_id, username, ConnectionState.DISCONNECTED
            )
            return False
        await asyncio.sleep(0.1)
    return True


async def connect_with_retry(
    shop_id: str,
    user_id: str,
    username: str,
    on_success: Callable,
    on_failure: Callable,
    *,
    reconnect_config: ReconnectConfig,
    stop_events: Dict[str, asyncio.Event],
    status_manager: ConnectionStatusManager,
    connect_attempt: ConnectAttemptFn,
    logger=None,
) -> None:
    """无限重连（max_attempts=0）或有限重试；固定间隔 ws_reconnect_delay_sec。"""
    log = logger or _logger
    key = connection_key(shop_id, user_id)
    attempt = 0
    max_attempts = reconnect_config.max_attempts

    while True:
        stop_ev = stop_events.get(key)
        if stop_ev and stop_ev.is_set():
            log.info(f"收到停止信号，取消重连: {shop_id}-{username}")
            status_manager.update_status(
                shop_id, user_id, username, ConnectionState.DISCONNECTED
            )
            return

        try:
            if attempt > 0:
                status_manager.update_status(
                    shop_id, user_id, username, ConnectionState.RECONNECTING
                )
                label = "∞" if max_attempts == 0 else str(max_attempts)
                log.info(
                    f"WebSocket 重连 ({attempt + 1}/{label}): {shop_id}-{username}"
                )
            await connect_attempt(
                shop_id, user_id, username, on_success, on_failure
            )
            if stop_ev and stop_ev.is_set():
                return
        except WsCredentialError as e:
            status_manager.update_status(
                shop_id, user_id, username, ConnectionState.ERROR, str(e)
            )
            log.error(f"WebSocket 凭证错误，停止重连: {shop_id}-{username}, {e}")
            on_failure(str(e))
            return
        except Exception as e:
            if stop_ev and stop_ev.is_set():
                status_manager.update_status(
                    shop_id, user_id, username, ConnectionState.DISCONNECTED
                )
                return
            status_manager.update_status(
                shop_id, user_id, username, ConnectionState.ERROR, str(e)
            )
            log.warning(f"WebSocket 连接异常: {shop_id}-{username}, {e}")

        if not reconnect_config.enable_auto_reconnect:
            on_failure("自动重连已禁用")
            return

        attempt += 1
        if max_attempts > 0 and attempt >= max_attempts:
            log.error(
                f"连接失败，已达最大重试 {max_attempts}: {shop_id}-{username}"
            )
            on_failure("连接失败，已达到最大重试次数")
            return

        base = reconnect_config.initial_delay or reconnect_config.reconnect_delay_sec
        factor = max(1.0, float(reconnect_config.backoff_factor or 1.0))
        delay = min(
            float(reconnect_config.max_delay or 60.0),
            base * (factor ** max(0, attempt - 1)),
        )
        delay += random.uniform(0, min(2.0, delay * 0.15))
        try:
            from core.app_metrics import record_ws_reconnect

            record_ws_reconnect()
        except Exception:
            pass
        log.info(f"{delay:.1f}s 后重连: {shop_id}-{username}")
        if not await interruptible_sleep(
            delay,
            connection_key=key,
            shop_id=shop_id,
            user_id=user_id,
            username=username,
            stop_events=stop_events,
            status_manager=status_manager,
            logger=log,
        ):
            return
