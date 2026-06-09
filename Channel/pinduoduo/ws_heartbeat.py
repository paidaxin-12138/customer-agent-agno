# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""WebSocket 心跳循环（从 pdd_chnnel 抽离，便于单测）。"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Optional

from Channel.pinduoduo.ws_config import HeartbeatConfig, connection_key
from core.connection_status import ConnectionState, ConnectionStatusManager
from utils.logger_loguru import get_logger

_logger = get_logger("WSHeartbeat")


async def run_heartbeat_loop(
    websocket: Any,
    shop_id: str,
    user_id: str,
    username: str,
    stop_event: asyncio.Event,
    *,
    config: HeartbeatConfig,
    status_manager: ConnectionStatusManager,
    on_finished: Optional[Callable[[str], None]] = None,
    logger=None,
) -> None:
    """周期性 ping WebSocket；连续失败达上限则标记 ERROR。"""
    log = logger or _logger
    key = connection_key(shop_id, user_id)
    consecutive_failures = 0

    try:
        while not stop_event.is_set():
            try:
                start_time = time.time()
                await websocket.ping()
                response_time = time.time() - start_time
                consecutive_failures = 0
                log.debug(
                    f"心跳成功: {shop_id}-{username}, 响应时间: {response_time:.3f}s"
                )

                status = status_manager.get_status(shop_id, user_id)
                if status and status.state == ConnectionState.CONNECTED:
                    pass

                await asyncio.sleep(config.heartbeat_interval)

            except asyncio.TimeoutError:
                consecutive_failures += 1
                log.warning(
                    f"心跳超时: {shop_id}-{username}, 连续失败: {consecutive_failures}"
                )
                await asyncio.sleep(config.heartbeat_timeout)

            except Exception as e:
                consecutive_failures += 1
                log.warning(
                    f"心跳失败: {shop_id}-{username}, 错误: {e}, "
                    f"连续失败: {consecutive_failures}"
                )

                if consecutive_failures >= config.max_heartbeat_failures:
                    log.error(
                        f"心跳检查失败次数过多，标记连接为错误状态: "
                        f"{shop_id}-{username}"
                    )
                    status_manager.update_status(
                        shop_id,
                        user_id,
                        username,
                        ConnectionState.ERROR,
                        f"心跳检查失败: 连续{consecutive_failures}次失败",
                    )
                    break

                await asyncio.sleep(config.heartbeat_timeout)

    except asyncio.CancelledError:
        log.debug(f"心跳循环被取消: {shop_id}-{username}")
    except Exception as e:
        log.error(f"心跳循环异常: {shop_id}-{username}, 错误: {e}")
    finally:
        if on_finished:
            on_finished(key)
        log.debug(f"心跳循环已结束: {shop_id}-{username}")
