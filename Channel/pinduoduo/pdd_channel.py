"""
拼多多 WebSocket 渠道（推荐入口）。

查询与全局状态请使用 ``core.channel_facade`` 或本模块 re-export 的辅助函数。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Set

import websockets
from config import config
from utils.logger_loguru import get_logger
from utils.resource_manager import WebSocketResourceManager

from Channel.channel import Channel
from Channel.pinduoduo.ws_account import (
    run_account_ws_connect,
    runtime_from_channel,
    start_account_for_channel,
    stop_account_for_channel,
)
from Channel.pinduoduo.ws_config import (
    HeartbeatConfig,
    PDD_WS_API_VERSION,
    load_reconnect_config,
    load_ws_message_concurrency,
)
from Channel.pinduoduo.ws_lifecycle import (
    cleanup_connection_resources,
    stop_all_connections as lifecycle_stop_all,
)
from Channel.pinduoduo.ws_task_cleanup import cancel_task_set
from core.channel_facade import (
    connection_summary,
    get_connected_count,
    heartbeat_status_all,
    list_connection_status,
)
from core.connection_status import ConnectionStatus, ConnectionStatusManager
from Channel.pinduoduo.ws_context import context_struct_payload as _context_struct_payload


class PDDChannel(Channel):
    """
    拼多多 WebSocket 客户端。

    每个 AutoReplyThread 独立实例；ConnectionStatusManager 经 DI 共享。
    """

    API_VERSION = PDD_WS_API_VERSION

    def __init__(
        self,
        max_concurrent_messages: Optional[int] = None,
        status_manager: ConnectionStatusManager = None,
    ):
        super().__init__()
        self.channel_name = "pinduoduo"
        self.logger = get_logger("PDDChannel")

        if status_manager is None:
            from core.di_container import container

            status_manager = container.get(ConnectionStatusManager)
        self.status_manager = status_manager

        self._stop_event: Optional[asyncio.Event] = None
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._stop_events: Dict[str, asyncio.Event] = {}
        self._ws_connections: Dict[str, websockets.WebSocketClientProtocol] = {}
        self.businessHours = config.get("business_hours") or config.get("businessHours")

        self.reconnect_config = load_reconnect_config()
        self.heartbeat_config = HeartbeatConfig()
        self._reconnect_tasks: Dict[str, asyncio.Task] = {}
        self._heartbeat_tasks: Dict[str, asyncio.Task] = {}

        if max_concurrent_messages is None:
            max_concurrent_messages = load_ws_message_concurrency()
        self.max_concurrent_messages = max_concurrent_messages
        self.message_semaphore = asyncio.Semaphore(max_concurrent_messages)
        self.processing_tasks: Set[asyncio.Task[Any]] = set()
        self.resource_manager = WebSocketResourceManager()

        from core.pdd_channel_registry import register_pdd_channel

        register_pdd_channel(self)

    async def start_account(
        self, shop_id: str, user_id: str, on_success: callable, on_failure: callable
    ) -> None:
        await start_account_for_channel(
            self, shop_id, user_id, on_success=on_success, on_failure=on_failure
        )

    async def stop_account(self, shop_id: str, user_id: str) -> None:
        try:
            await stop_account_for_channel(self, shop_id, user_id)
        except Exception as exc:
            self.logger.error(f"停止店铺 {shop_id} 账号 {user_id} 时发生错误: {exc}")

    async def init(
        self, shop_id: str, user_id: str, username: str, on_success: callable, on_failure: callable
    ) -> None:
        await run_account_ws_connect(
            shop_id,
            user_id,
            username,
            runtime=runtime_from_channel(self),
            on_success=on_success,
            on_failure=on_failure,
            on_inbound=self._on_inbound_ws_message,
        )

    async def _connect_single_attempt(
        self, shop_id: str, user_id: str, username: str, on_success: callable, on_failure: callable
    ) -> None:
        await self.init(shop_id, user_id, username, on_success, on_failure)

    async def _on_inbound_ws_message(
        self, message: str, shop_id: str, user_id: str, username: str, queue_name: str
    ) -> None:
        from Channel.pinduoduo.ws_inbound_pipeline import run_inbound_for_channel

        await run_inbound_for_channel(
            self, message, shop_id, user_id, username, queue_name
        )

    async def cleanup_processing_tasks(self) -> None:
        await cancel_task_set(self.processing_tasks, logger=self.logger)

    def request_stop(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        for event in self._stop_events.values():
            event.set()

    async def stop_all_connections(self) -> None:
        await lifecycle_stop_all(
            stop_event=self._stop_event,
            stop_events=self._stop_events,
            reconnect_tasks=self._reconnect_tasks,
            heartbeat_tasks=self._heartbeat_tasks,
            ws_connections=self._ws_connections,
            logger=self.logger,
        )
        self.ws = None

    async def close_websocket(self) -> None:
        """关闭全部 WebSocket 连接并取消心跳/重连循环。"""
        self.request_stop()
        try:
            await self.stop_all_connections()
        finally:
            await self.cleanup_processing_tasks()
        self.ws = None

    async def _cleanup_resources(
        self,
        queue_name: str,
        connection_key: Optional[str] = None,
        *,
        keep_consumer: bool = False,
    ) -> None:
        await cleanup_connection_resources(
            queue_name=queue_name,
            connection_key=connection_key,
            keep_consumer=keep_consumer,
            reconnect_tasks=self._reconnect_tasks,
            heartbeat_tasks=self._heartbeat_tasks,
            ws_connections=self._ws_connections,
            stop_events=self._stop_events,
            processing_tasks=self.processing_tasks,
            resource_manager=self.resource_manager,
            logger=self.logger,
        )


def get_pdd_connection_status() -> List[ConnectionStatus]:
    return list_connection_status()


def get_pdd_connected_count() -> int:
    return get_connected_count()


def get_pdd_connection_summary() -> Dict[str, int]:
    return connection_summary()


def get_pdd_heartbeat_status_all() -> Dict[str, Dict]:
    return heartbeat_status_all()


__all__ = [
    "PDDChannel",
    "_context_struct_payload",
    "get_pdd_connected_count",
    "get_pdd_connection_status",
    "get_pdd_connection_summary",
    "get_pdd_heartbeat_status_all",
]
