"""单账号 WebSocket 启停与会话（从 PDDChannel 抽离）。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional, Set

from websockets import exceptions as ws_exceptions

from Channel.pinduoduo.utils.API.get_token import GetToken
from Channel.pinduoduo.ws_config import (
    HeartbeatConfig,
    ReconnectConfig,
    connection_key,
    queue_name_for_account,
)
from Channel.pinduoduo.ws_auth_notify import (
    clear_auth_callbacks,
    pop_fatal_auth_message,
    register_auth_stop_callback,
    register_auth_success_callback,
)
from Channel.pinduoduo.ws_connect import connect_pdd_ws
from Channel.pinduoduo.ws_errors import WsCredentialError
from database import db_manager
from Channel.pinduoduo.ws_connect_session import is_ws_closed, run_connected_session
from Channel.pinduoduo.ws_consumer_setup import setup_message_consumer
from Channel.pinduoduo.ws_online import set_account_online
from Channel.pinduoduo.ws_reconnect import connect_with_retry
from Channel.pinduoduo.ws_lifecycle import stop_single_account
from core.connection_status import ConnectionState, ConnectionStatusManager
from utils.logger_loguru import get_logger

_logger = get_logger("WSAccount")

ConnectAttemptFn = Callable[
    [str, str, str, Callable, Callable],
    Awaitable[None],
]
InboundFn = Callable[[str, str, str, str, str], Awaitable[None]]
CleanupFn = Callable[..., Awaitable[None]]


def resolve_pdd_account(
    channel_name: str, shop_id: str, user_id: str
) -> tuple[Optional[str], Optional[dict]]:
    """返回 (login_username, account_row)；不存在时 username 为 None。"""
    row = db_manager.get_account(channel_name, shop_id, user_id)
    if not row:
        return None, None
    return str(row.get("username") or user_id), row


async def start_account_for_channel(
    channel: Any,
    shop_id: str,
    user_id: str,
    *,
    on_success: Callable,
    on_failure: Callable,
) -> None:
    username, row = resolve_pdd_account(channel.channel_name, shop_id, user_id)
    if row is None:
        error_msg = f"账号 {user_id} 在数据库中不存在"
        channel.logger.error(error_msg)
        on_failure(error_msg)
        return
    await launch_account_connect(
        shop_id,
        user_id,
        username,
        runtime=runtime_from_channel(channel),
        connect_attempt=channel._connect_single_attempt,
        on_success=on_success,
        on_failure=on_failure,
    )


async def stop_account_for_channel(channel: Any, shop_id: str, user_id: str) -> None:
    username, row = resolve_pdd_account(channel.channel_name, shop_id, user_id)
    if row is None:
        channel.logger.warning(f"账号 {user_id} 不存在，无法停止")
        return
    await stop_single_account(
        shop_id,
        user_id,
        username,
        status_manager=channel.status_manager,
        stop_events=channel._stop_events,
        cleanup_resources=channel._cleanup_resources,
        queue_name=queue_name_for_account(shop_id, user_id),
        logger=channel.logger,
    )
    channel.ws = None


@dataclass
class PDDChannelRuntime:
    """PDDChannel 实例上的连接运行时引用（避免 ws 模块反向依赖 Channel 类）。"""

    channel_name: str
    logger: Any
    status_manager: ConnectionStatusManager
    reconnect_config: ReconnectConfig
    heartbeat_config: HeartbeatConfig
    stop_events: Dict[str, asyncio.Event]
    reconnect_tasks: Dict[str, asyncio.Task]
    heartbeat_tasks: Dict[str, asyncio.Task]
    ws_connections: Dict[str, Any]
    processing_tasks: Set[asyncio.Task]
    resource_manager: Any
    business_hours: Any
    message_semaphore: asyncio.Semaphore
    cleanup_resources: CleanupFn
    _channel: Any = field(default=None, repr=False)
    ws: Optional[Any] = field(default=None, repr=False)
    stop_event: Optional[asyncio.Event] = field(default=None, repr=False)

    def bind_ws(self, websocket: Any) -> None:
        self.ws = websocket
        if self._channel is not None:
            self._channel.ws = websocket

    def clear_ws(self) -> None:
        self.ws = None
        if self._channel is not None:
            self._channel.ws = None

    def bind_stop_event(self, event: asyncio.Event) -> None:
        self.stop_event = event
        if self._channel is not None:
            self._channel._stop_event = event


def runtime_from_channel(channel: Any) -> PDDChannelRuntime:
    return PDDChannelRuntime(
        channel_name=channel.channel_name,
        logger=channel.logger,
        status_manager=channel.status_manager,
        reconnect_config=channel.reconnect_config,
        heartbeat_config=channel.heartbeat_config,
        stop_events=channel._stop_events,
        reconnect_tasks=channel._reconnect_tasks,
        heartbeat_tasks=channel._heartbeat_tasks,
        ws_connections=channel._ws_connections,
        processing_tasks=channel.processing_tasks,
        resource_manager=channel.resource_manager,
        business_hours=channel.businessHours,
        message_semaphore=channel.message_semaphore,
        cleanup_resources=channel._cleanup_resources,
        _channel=channel,
        ws=channel.ws,
        stop_event=channel._stop_event,
    )


async def launch_account_connect(
    shop_id: str,
    user_id: str,
    username: str,
    *,
    runtime: PDDChannelRuntime,
    connect_attempt: ConnectAttemptFn,
    on_success: Callable,
    on_failure: Callable,
) -> None:
    """启动账号连接任务（含可选自动重连）。"""
    key = connection_key(shop_id, user_id)
    runtime.stop_events[key] = asyncio.Event()
    runtime.status_manager.update_status(
        shop_id, user_id, username, ConnectionState.CONNECTING
    )

    if key in runtime.reconnect_tasks:
        runtime.reconnect_tasks[key].cancel()
        del runtime.reconnect_tasks[key]

    if runtime.reconnect_config.enable_auto_reconnect:
        task = asyncio.create_task(
            connect_with_retry(
                shop_id,
                user_id,
                username,
                on_success,
                on_failure,
                reconnect_config=runtime.reconnect_config,
                stop_events=runtime.stop_events,
                status_manager=runtime.status_manager,
                connect_attempt=connect_attempt,
                logger=runtime.logger,
            )
        )
    else:
        task = asyncio.create_task(
            connect_attempt(shop_id, user_id, username, on_success, on_failure)
        )
    runtime.reconnect_tasks[key] = task


async def run_account_ws_connect(
    shop_id: str,
    user_id: str,
    username: str,
    *,
    runtime: PDDChannelRuntime,
    on_success: Callable,
    on_failure: Callable,
    on_inbound: InboundFn,
) -> None:
    """单次 WebSocket 建连 → 上线 → 心跳/消息循环。"""
    log = runtime.logger or _logger
    key = connection_key(shop_id, user_id)
    queue_name = queue_name_for_account(shop_id, user_id)

    try:
        stop_event = runtime.stop_events.get(key) or asyncio.Event()
        runtime.stop_events[key] = stop_event
        runtime.bind_stop_event(stop_event)

        register_auth_success_callback(key, on_success)
        register_auth_stop_callback(key, stop_event.set)

        access_token = await asyncio.to_thread(
            GetToken(shop_id, user_id, runtime.channel_name).get_token
        )
        if not access_token:
            raise WsCredentialError(
                f"无法获取 WebSocket Token（账号 {username}），"
                "请在「用户管理」重新登录后再开始回复。"
            )

        await setup_message_consumer(
            queue_name,
            business_hours=runtime.business_hours,
            logger=log,
        )

        log.debug(f"正在连接到拼多多WebSocket: {shop_id}-{username}")

        async with connect_pdd_ws(access_token) as websocket:
            runtime.bind_ws(websocket)
            runtime.ws_connections[key] = websocket
            runtime.resource_manager.register_websocket(
                websocket, f"PDD WebSocket ({shop_id}-{username})"
            )
            log.debug(f"WebSocket连接已建立: {shop_id}-{username}")

            if runtime.ws and not is_ws_closed(runtime.ws):
                log.debug(f"WebSocket连接正常: {shop_id}-{username}")
            else:
                log.error(f"WebSocket连接异常: {shop_id}-{username}")

            runtime.status_manager.update_status(
                shop_id, user_id, username, ConnectionState.CONNECTED
            )

            try:
                if await set_account_online(
                    runtime.channel_name, shop_id, user_id, logger=log
                ):
                    log.info(f"在线状态设置成功：{shop_id}-{username}")
                else:
                    log.warning(f"在线状态 API 未成功：{shop_id}-{username}")
            except Exception as exc:
                log.warning(f"在线状态设置异常：{shop_id}-{username}, {exc}")

            async def _on_session_end() -> None:
                await runtime.cleanup_resources(
                    queue_name, connection_key=key, keep_consumer=True
                )
                runtime.clear_ws()

            await run_connected_session(
                websocket,
                shop_id=shop_id,
                user_id=user_id,
                username=username,
                stop_event=stop_event,
                heartbeat_config=runtime.heartbeat_config,
                heartbeat_tasks=runtime.heartbeat_tasks,
                processing_tasks=runtime.processing_tasks,
                status_manager=runtime.status_manager,
                on_message=lambda msg: on_inbound(
                    msg, shop_id, user_id, username, queue_name
                ),
                on_cleanup=_on_session_end,
                logger=log,
            )

        fatal = pop_fatal_auth_message(key)
        if fatal:
            raise WsCredentialError(fatal)

    except WsCredentialError as exc:
        runtime.status_manager.update_status(
            shop_id, user_id, username, ConnectionState.ERROR, str(exc)
        )
        log.error(f"WebSocket 凭证无效: {shop_id}-{username}, {exc}")
        stop_ev = runtime.stop_events.get(key)
        if stop_ev is not None:
            stop_ev.set()
        on_failure(str(exc))
        await runtime.cleanup_resources(
            queue_name, connection_key=key, keep_consumer=True
        )
        raise
    except ws_exceptions.ConnectionClosed as exc:
        runtime.status_manager.update_status(
            shop_id, user_id, username, ConnectionState.ERROR, str(exc)
        )
        log.warning(f"WebSocket连接已关闭: {shop_id}-{username}, 错误: {exc}")
        on_failure(f"WebSocket连接已关闭: {exc}")
    except Exception as exc:
        runtime.status_manager.update_status(
            shop_id, user_id, username, ConnectionState.ERROR, str(exc)
        )
        log.error(f"WebSocket连接错误: {shop_id}-{username}, 错误: {exc}")
        on_failure(f"WebSocket连接错误: {exc}")
        await runtime.cleanup_resources(
            queue_name, connection_key=key, keep_consumer=True
        )
    finally:
        clear_auth_callbacks(key)
