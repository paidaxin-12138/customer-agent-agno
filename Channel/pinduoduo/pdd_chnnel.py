"""
拼多多WebSocket客户端
此模块提供与拼多多商家后台的WebSocket通信功能，用于接收和发送客服消息。
支持多店铺管理、消息队列处理和自动重连机制。
"""
from utils.logger_loguru import get_logger
from bridge.context import Context, ContextType, ChannelType
from Channel.pinduoduo.pdd_message import PDDChatMessage
from Channel.channel import Channel
from Channel.pinduoduo.utils.API.get_token import GetToken
from database import db_manager
from utils.resource_manager import WebSocketResourceManager
from core.connection_status import ConnectionStatusManager, ConnectionState, ConnectionStatus
import websockets
import json
from websockets import exceptions as ws_exceptions
import asyncio
import time
from typing import Optional, Dict, List, Set, Any
from dataclasses import dataclass
# 延迟导入 Message 模块，避免模块级循环依赖
from config import config


def _context_struct_payload(context: Context) -> Dict[str, Any]:
    """解析 Context.content；入队前 dict 会被 json.dumps 成字符串。"""
    raw = context.content
    if isinstance(raw, dict):
        return raw
    if not raw or not isinstance(raw, str):
        return {}
    text = raw.strip()
    if not text.startswith("{"):
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ============================================================================
# WebSocket优化组件 - 自动重连配置
# ============================================================================

@dataclass
class ReconnectConfig:
    """重连配置（max_attempts=0 表示无限重试）"""
    max_attempts: int = 0
    reconnect_delay_sec: float = 5.0
    initial_delay: float = 5.0
    max_delay: float = 60.0
    backoff_factor: float = 1.0
    enable_auto_reconnect: bool = True

@dataclass
class HeartbeatConfig:
    """心跳检查配置"""
    enable_heartbeat: bool = True     # 是否启用心跳检查
    heartbeat_interval: float = 30.0   # 心跳间隔(秒)
    heartbeat_timeout: float = 10.0    # 心跳超时(秒)
    health_check_interval: float = 60.0 # 健康检查间隔(秒)
    max_heartbeat_failures: int = 3    # 最大心跳失败次数

class PDDChannel(Channel):
    """
    拼多多WebSocket客户端 - 支持自动重连和心跳检查

    注意：此类不再强制单例。每个 AutoReplyThread 应创建独立的 PDDChannel 实例
    （各自的事件循环 + WebSocket 连接），但通过 DI 容器共享同一个
    ConnectionStatusManager 来维护全局连接状态。
    """

    # API 版本号
    API_VERSION = "202506091557"

    def __init__(
        self,
        max_concurrent_messages: Optional[int] = None,
        status_manager: ConnectionStatusManager = None,
    ):
        super().__init__()
        self.channel_name = "pinduoduo"
        self.logger = get_logger("PDDChannel")

        # 从 DI 容器获取 ConnectionStatusManager（所有实例共享同一个）
        if status_manager is None:
            from core.di_container import container
            status_manager = container.get(ConnectionStatusManager)
        self.status_manager = status_manager

        self._stop_event: Optional[asyncio.Event] = None
        self.base_url = "wss://m-ws.pinduoduo.com/"
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._stop_events: Dict[str, asyncio.Event] = {}
        self._ws_connections: Dict[str, websockets.WebSocketClientProtocol] = {}
        self.businessHours = config.get("business_hours") or config.get("businessHours")

        # WebSocket优化功能
        self.reconnect_config = self._load_reconnect_config()
        self.heartbeat_config = HeartbeatConfig()
        self._reconnect_tasks: Dict[str, asyncio.Task] = {}
        self._heartbeat_tasks: Dict[str, asyncio.Task] = {}

        # 性能优化：并发控制和任务管理（默认读 chat.ws_message_max_concurrent）
        if max_concurrent_messages is None:
            try:
                from config import get_config

                max_concurrent_messages = int(
                    get_config("chat.ws_message_max_concurrent", 16) or 16
                )
            except (TypeError, ValueError):
                max_concurrent_messages = 16
            max_concurrent_messages = max(4, min(max_concurrent_messages, 32))
        self.max_concurrent_messages = max_concurrent_messages
        self.message_semaphore = asyncio.Semaphore(max_concurrent_messages)
        self.processing_tasks: Set[asyncio.Task[Any]] = set()

        # 资源管理
        self.resource_manager = WebSocketResourceManager()

    def _load_reconnect_config(self) -> ReconnectConfig:
        cfg = ReconnectConfig()
        try:
            from config import get_config

            delay = float(get_config("chat.ws_reconnect_delay_sec", 5) or 5)
            cfg.reconnect_delay_sec = max(3.0, min(delay, 120.0))
            cfg.initial_delay = cfg.reconnect_delay_sec
            max_att = int(get_config("chat.ws_reconnect_max_attempts", 0) or 0)
            cfg.max_attempts = max(0, max_att)
            cfg.enable_auto_reconnect = bool(
                get_config("chat.ws_auto_reconnect_enabled", True)
            )
        except (TypeError, ValueError):
            pass
        return cfg

    async def _set_online_status(self, shop_id: str, user_id: str) -> bool:
        """
        WebSocket 连通后调用 MMS `set_csstatus`，与自动回复「上线」一致。
        使用线程执行同步 BaseRequest.post，避免阻塞事件循环。
        """
        account_info = db_manager.get_account(self.channel_name, str(shop_id), str(user_id))
        if not account_info:
            self.logger.warning("_set_online_status: 无账号记录 shop_id={} user_id={}", shop_id, user_id)
            return False
        cookies = account_info.get("cookies")
        if not cookies:
            self.logger.warning("_set_online_status: 账号缺少 cookies shop_id={} user_id={}", shop_id, user_id)
            return False

        def _sync_set() -> bool:
            from Channel.pinduoduo.utils.API.Set_up_online import AccountMonitor

            mon = AccountMonitor(cookies)
            return bool(mon.set_csstatus(1))

        return await asyncio.to_thread(_sync_set)

    async def start_account(self, shop_id: str, user_id: str, on_success: callable, on_failure: callable) -> None:
        """
        启动指定店铺下账号 - 支持自动重连
        :param shop_id: 店铺ID
        :param user_id: 用户ID
        :param on_success: 连接成功回调
        :param on_failure: 连接失败回调
        """
        account_info = db_manager.get_account(self.channel_name, shop_id, user_id)
        if not account_info:
            error_msg = f"账号 {user_id} 在数据库中不存在"
            self.logger.error(error_msg)
            on_failure(error_msg)
            return

        username = account_info.get("username", user_id)
        connection_key = f"{shop_id}_{user_id}"
        self._stop_events[connection_key] = asyncio.Event()

        # 更新状态为连接中
        self.status_manager.update_status(shop_id, user_id, username, ConnectionState.CONNECTING)

        # 如果已存在重连任务，先取消
        if connection_key in self._reconnect_tasks:
            self._reconnect_tasks[connection_key].cancel()
            del self._reconnect_tasks[connection_key]

        # 创建带重连的连接任务
        if self.reconnect_config.enable_auto_reconnect:
            connect_task = asyncio.create_task(
                self._connect_with_retry(shop_id, user_id, username, on_success, on_failure)
            )
        else:
            connect_task = asyncio.create_task(
                self._connect_single_attempt(shop_id, user_id, username, on_success, on_failure)
            )

        self._reconnect_tasks[connection_key] = connect_task

    async def stop_account(self, shop_id: str, user_id: str) -> None:
        """
        停止指定店铺下账号 - 增强版支持重连任务清理
        :param shop_id: 店铺ID
        :param user_id: 用户ID
        """
        try:
            # 检查账号是否存在
            account_info = db_manager.get_account(self.channel_name, shop_id, user_id)
            if not account_info:
                self.logger.warning(f"账号 {user_id} 不存在，无法停止")
                return

            username = account_info.get("username", user_id)
            connection_key = f"{shop_id}_{user_id}"

            self.logger.info(f"正在停止店铺 {shop_id} 账号 {username}")

            # 设置该账号停止事件，避免影响其他账号
            stop_event = self._stop_events.get(connection_key)
            if stop_event:
                stop_event.set()

            # 取消并等待重连任务完成
            if connection_key in self._reconnect_tasks:
                task = self._reconnect_tasks[connection_key]
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=5.0)
                    except asyncio.CancelledError:
                        self.logger.debug(f"重连任务已被取消: {connection_key}")
                    except asyncio.TimeoutError:
                        self.logger.warning(f"重连任务取消超时: {connection_key}")
                    except Exception as task_error:
                        self.logger.error(f"等待重连任务完成时出错: {task_error}")
                del self._reconnect_tasks[connection_key]
                self.logger.debug(f"已清理重连任务: {connection_key}")

            # 取消并等待心跳任务完成
            if connection_key in self._heartbeat_tasks:
                task = self._heartbeat_tasks[connection_key]
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=3.0)
                    except asyncio.CancelledError:
                        self.logger.debug(f"心跳任务已被取消: {connection_key}")
                    except asyncio.TimeoutError:
                        self.logger.warning(f"心跳任务取消超时: {connection_key}")
                    except Exception as task_error:
                        self.logger.error(f"等待心跳任务完成时出错: {task_error}")
                del self._heartbeat_tasks[connection_key]
                self.logger.debug(f"已清理心跳任务: {connection_key}")

            # 更新状态为断开
            self.status_manager.update_status(shop_id, user_id, username, ConnectionState.DISCONNECTED)

            # 关闭该账号WebSocket连接
            ws = self._ws_connections.pop(connection_key, None)
            if ws:
                await self._safe_close_websocket(ws)
                self.logger.info(f"已关闭店铺 {shop_id} 账号 {username} 的WebSocket连接")
            else:
                self.logger.warning(f"店铺 {shop_id} 账号 {username} 的WebSocket连接已经关闭或不存在")

            # 清理并发处理任务
            await self.cleanup_processing_tasks()

            # 按账号粒度清理资源与消费者
            queue_name = f"pdd_{shop_id}"
            await self._cleanup_resources(queue_name, connection_key=connection_key)

            # 清理该账号stop token
            self._stop_events.pop(connection_key, None)

            self.logger.info(f"成功停止店铺 {shop_id} 账号 {username}")

        except Exception as e:
            self.logger.error(f"停止店铺 {shop_id} 账号 {user_id} 时发生错误: {str(e)}")


    async def init(self, shop_id: str, user_id: str, username: str, on_success: callable, on_failure: callable) -> None:
        """
        初始化WebSocket连接和消息处理系统
        """
        try:
            # 使用账号级停止事件，避免全局停止信号影响其他账号
            connection_key = f"{shop_id}_{user_id}"
            stop_event = self._stop_events.get(connection_key) or asyncio.Event()
            self._stop_events[connection_key] = stop_event
            # 兼容旧逻辑中仍访问 self._stop_event 的路径
            self._stop_event = stop_event
            
            # 获取访问令牌
            token = GetToken(shop_id, user_id)
            access_token = token.get_token()
            
            # 设置队列名称
            queue_name = f"pdd_{shop_id}"
            
            # 初始化消息消费者和处理器（只创建一次）
            await self._setup_message_consumer(queue_name)
            
            # 构建WebSocket连接URL
            params = {
                "access_token": access_token,
                "role": "mall_cs",
                "client": "web",
                "version": PDDChannel.API_VERSION
            }
            query = "&".join([f"{k}={v}" for k, v in params.items()])
            full_url = f"{self.base_url}?{query}"
            
            self.logger.debug(f"正在连接到拼多多WebSocket: {shop_id}-{username}")
            
            # 建立WebSocket连接
            async with websockets.connect(
                full_url,
                ping_interval=60,  # 增加到60秒，避免与平台要求冲突
                ping_timeout=30,   # 增加超时时间，提高容错性
                max_size=10**7,    # 10MB消息大小限制
                compression=None,  # 禁用压缩，减少延迟
                close_timeout=10   # 设置关闭超时
            ) as websocket:
                self.ws = websocket
                self._ws_connections[connection_key] = websocket
                # 注册WebSocket连接到资源管理器
                self.resource_manager.register_websocket(
                    websocket,
                    f"PDD WebSocket ({shop_id}-{username})"
                )
                self.logger.debug(f"WebSocket连接已建立: {shop_id}-{username}")



                # 检查WebSocket连接状态
                if self.ws and not self._is_ws_closed(self.ws):
                    self.logger.debug(f"WebSocket连接正常: {shop_id}-{username}")
                else:
                    self.logger.error(f"WebSocket连接异常: {shop_id}-{username}")

                # 连接成功，更新状态并调用成功回调
                self.status_manager.update_status(shop_id, user_id, username, ConnectionState.CONNECTED)

                # 设置在线状态（与自动回复「上线」同一 MMS 接口）
                try:
                    if await self._set_online_status(shop_id, user_id):
                        self.logger.info(f"在线状态设置成功：{shop_id}-{username}")
                    else:
                        self.logger.warning(f"在线状态 API 未成功：{shop_id}-{username}")
                except Exception as e:
                    self.logger.warning(f"在线状态设置异常：{shop_id}-{username}, {e}")
                    # 不影响连接，继续执行

                on_success()

                # 启动心跳检查任务
                heartbeat_task = None
                if self.heartbeat_config.enable_heartbeat:
                    connection_key = f"{shop_id}_{user_id}"
                    heartbeat_task = asyncio.create_task(
                        self._heartbeat_loop(websocket, shop_id, user_id, username, stop_event)
                    )
                    self._heartbeat_tasks[connection_key] = heartbeat_task
                    self.logger.debug(f"心跳检查已启动: {shop_id}-{username}")

                # 创建消息接收任务
                message_task = asyncio.create_task(
                    self._message_loop(websocket, shop_id, user_id, username, queue_name, stop_event)
                )

                # 等待停止事件或消息任务完成
                stop_task = asyncio.create_task(stop_event.wait())

                try:
                    # 收集所有需要监控的任务
                    tasks = [message_task, stop_task]
                    if heartbeat_task:
                        tasks.append(heartbeat_task)

                    done, pending = await asyncio.wait(
                        tasks,
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    # 判断是否应该清理资源
                    should_cleanup = False
                    if stop_task in done:
                        self.logger.debug(f"收到停止信号: {shop_id}-{username}")
                        should_cleanup = True
                    else:
                        # 消息循环或心跳异常结束（不是正常停止）
                        self.logger.warning(f"消息循环异常结束: {shop_id}-{username}")
                        should_cleanup = True

                    # 取消未完成的任务
                    for task in pending:
                        task.cancel()
                        try:
                            await asyncio.wait_for(task, timeout=3.0)
                        except (asyncio.CancelledError, asyncio.TimeoutError, asyncio.InvalidStateError):
                            pass
                        except Exception as e:
                            self.logger.debug(f"等待任务取消时出错: {e}")

                    # 只在需要时清理资源
                    if should_cleanup:
                        await self._cleanup_resources(
                            f"pdd_{shop_id}",
                            connection_key=connection_key,
                            keep_consumer=True,
                        )

                except asyncio.CancelledError:
                    self.logger.debug(f"WebSocket任务被取消: {shop_id}-{username}")
                    message_task.cancel()
                    if heartbeat_task:
                        heartbeat_task.cancel()
                    try:
                        await asyncio.wait_for(message_task, timeout=3.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError, asyncio.InvalidStateError):
                        pass
                    if heartbeat_task:
                        try:
                            await asyncio.wait_for(heartbeat_task, timeout=3.0)
                        except (asyncio.CancelledError, asyncio.TimeoutError, asyncio.InvalidStateError):
                            pass
                    await self._cleanup_resources(
                        f"pdd_{shop_id}",
                        connection_key=connection_key,
                        keep_consumer=True,
                    )

        except ws_exceptions.ConnectionClosed as e:
            self.status_manager.update_status(shop_id, user_id, username, ConnectionState.ERROR, str(e))
            self.logger.warning(f"WebSocket连接已关闭: {shop_id}-{username}, 错误: {str(e)}")
            on_failure(f"WebSocket连接已关闭: {e}")
        except Exception as e:
            self.status_manager.update_status(shop_id, user_id, username, ConnectionState.ERROR, str(e))
            self.logger.error(f"WebSocket连接错误: {shop_id}-{username}, 错误: {str(e)}")
            on_failure(f"WebSocket连接错误: {e}")
            # 异常时也需要清理资源
            await self._cleanup_resources(
                f"pdd_{shop_id}",
                connection_key=connection_key,
                keep_consumer=True,
            )

    # ============================================================================
    # WebSocket优化功能 - 自动重连和单次连接方法
    # ============================================================================

    async def _interruptible_sleep(self, delay: float, connection_key: str, shop_id: str, user_id: str, username: str) -> bool:
        """可中断等待；返回 False 表示应停止重连。"""
        stop_ev = self._stop_events.get(connection_key)
        steps = max(1, int(delay * 10))
        for _ in range(steps):
            if stop_ev and stop_ev.is_set():
                self.logger.info(f"重连等待被停止信号中断: {shop_id}-{username}")
                self.status_manager.update_status(
                    shop_id, user_id, username, ConnectionState.DISCONNECTED
                )
                return False
            await asyncio.sleep(0.1)
        return True

    async def _connect_with_retry(
        self,
        shop_id: str,
        user_id: str,
        username: str,
        on_success: callable,
        on_failure: callable,
    ):
        """无限重连（max_attempts=0）或有限重试；固定间隔 ws_reconnect_delay_sec。"""
        connection_key = f"{shop_id}_{user_id}"
        attempt = 0
        max_attempts = self.reconnect_config.max_attempts

        while True:
            stop_ev = self._stop_events.get(connection_key)
            if stop_ev and stop_ev.is_set():
                self.logger.info(f"收到停止信号，取消重连: {shop_id}-{username}")
                self.status_manager.update_status(
                    shop_id, user_id, username, ConnectionState.DISCONNECTED
                )
                return

            try:
                if attempt > 0:
                    self.status_manager.update_status(
                        shop_id, user_id, username, ConnectionState.RECONNECTING
                    )
                    label = "∞" if max_attempts == 0 else str(max_attempts)
                    self.logger.info(
                        f"WebSocket 重连 ({attempt + 1}/{label}): {shop_id}-{username}"
                    )
                await self._connect_single_attempt(
                    shop_id, user_id, username, on_success, on_failure
                )
                if stop_ev and stop_ev.is_set():
                    return
            except Exception as e:
                if stop_ev and stop_ev.is_set():
                    self.status_manager.update_status(
                        shop_id, user_id, username, ConnectionState.DISCONNECTED
                    )
                    return
                self.status_manager.update_status(
                    shop_id, user_id, username, ConnectionState.ERROR, str(e)
                )
                self.logger.warning(
                    f"WebSocket 连接异常: {shop_id}-{username}, {e}"
                )

            if not self.reconnect_config.enable_auto_reconnect:
                on_failure("自动重连已禁用")
                return

            attempt += 1
            if max_attempts > 0 and attempt >= max_attempts:
                self.logger.error(
                    f"连接失败，已达最大重试 {max_attempts}: {shop_id}-{username}"
                )
                on_failure(f"连接失败，已达到最大重试次数")
                return

            delay = self.reconnect_config.reconnect_delay_sec
            self.logger.info(f"{delay:.0f}s 后重连: {shop_id}-{username}")
            if not await self._interruptible_sleep(
                delay, connection_key, shop_id, user_id, username
            ):
                return

    async def _connect_single_attempt(self, shop_id: str, user_id: str, username: str, on_success: callable, on_failure: callable):
        """
        单次WebSocket连接尝试
        """
        # 调用原有的init方法进行单次连接
        await self.init(shop_id, user_id, username, on_success, on_failure)

    # ============================================================================
    # WebSocket优化功能 - 公共API接口
    # ============================================================================

    def get_connection_status(self) -> List[ConnectionStatus]:
        """
        获取所有连接状态 - 供外部模块调用
        Returns:
            List[ConnectionStatus]: 所有连接的状态信息列表
        """
        return self.status_manager.get_all_status()

    def get_connected_count(self) -> int:
        """
        获取当前连接数 - 供外部模块调用
        Returns:
            int: 当前活跃连接数
        """
        return self.status_manager.get_connected_count()

    def get_connection_info(self, shop_id: str, user_id: str) -> Optional[ConnectionStatus]:
        """
        获取指定连接的状态信息 - 供外部模块调用
        Args:
            shop_id: 店铺ID
            user_id: 用户ID
        Returns:
            Optional[ConnectionStatus]: 连接状态信息，如果不存在返回None
        """
        return self.status_manager.get_status(shop_id, user_id)

    def configure_reconnect(self, max_attempts: int = None, initial_delay: float = None,
                          max_delay: float = None, backoff_factor: float = None,
                          enable_auto_reconnect: bool = None) -> None:
        """
        配置重连参数 - 供外部模块调用
        Args:
            max_attempts: 最大重试次数
            initial_delay: 初始延迟(秒)
            max_delay: 最大延迟(秒)
            backoff_factor: 退避因子
            enable_auto_reconnect: 是否启用自动重连
        """
        if max_attempts is not None:
            self.reconnect_config.max_attempts = max_attempts
        if initial_delay is not None:
            self.reconnect_config.initial_delay = initial_delay
        if max_delay is not None:
            self.reconnect_config.max_delay = max_delay
        if backoff_factor is not None:
            self.reconnect_config.backoff_factor = backoff_factor
        if enable_auto_reconnect is not None:
            self.reconnect_config.enable_auto_reconnect = enable_auto_reconnect

        self.logger.info(f"重连配置已更新: max_attempts={self.reconnect_config.max_attempts}, "
                        f"initial_delay={self.reconnect_config.initial_delay}, "
                        f"enable_auto_reconnect={self.reconnect_config.enable_auto_reconnect}")

    def configure_heartbeat(self, enable_heartbeat: bool = None, heartbeat_interval: float = None,
                           heartbeat_timeout: float = None, max_heartbeat_failures: int = None) -> None:
        """
        配置心跳参数 - 供外部模块调用
        Args:
            enable_heartbeat: 是否启用心跳检查
            heartbeat_interval: 心跳间隔(秒)
            heartbeat_timeout: 心跳超时(秒)
            max_heartbeat_failures: 最大心跳失败次数
        """
        if enable_heartbeat is not None:
            self.heartbeat_config.enable_heartbeat = enable_heartbeat
        if heartbeat_interval is not None:
            self.heartbeat_config.heartbeat_interval = heartbeat_interval
        if heartbeat_timeout is not None:
            self.heartbeat_config.heartbeat_timeout = heartbeat_timeout
        if max_heartbeat_failures is not None:
            self.heartbeat_config.max_heartbeat_failures = max_heartbeat_failures

        self.logger.info(f"心跳配置已更新: enable_heartbeat={self.heartbeat_config.enable_heartbeat}, "
                        f"heartbeat_interval={self.heartbeat_config.heartbeat_interval}, "
                        f"max_heartbeat_failures={self.heartbeat_config.max_heartbeat_failures}")

    def get_heartbeat_status(self, shop_id: str, user_id: str) -> Dict[str, Optional[any]]:
        """
        获取心跳状态信息 - 供外部模块调用
        Args:
            shop_id: 店铺ID
            user_id: 用户ID
        Returns:
            Dict[str, Optional[any]]: 心跳状态信息
        """
        connection_key = f"{shop_id}_{user_id}"
        has_heartbeat_task = connection_key in self._heartbeat_tasks

        status = self.status_manager.get_status(shop_id, user_id)

        return {
            "connection_key": connection_key,
            "heartbeat_enabled": self.heartbeat_config.enable_heartbeat,
            "heartbeat_running": has_heartbeat_task,
            "heartbeat_interval": self.heartbeat_config.heartbeat_interval,
            "max_failures": self.heartbeat_config.max_heartbeat_failures,
            "connection_state": status.state.value if status else None,
            "last_error": status.last_error if status else None,
            "error_count": status.error_count if status else 0
        }

    # ============================================================================
    # WebSocket心跳检查功能
    # ============================================================================

    async def _heartbeat_loop(self, websocket, shop_id: str, user_id: str, username: str, stop_event: asyncio.Event):
        """
        心跳检查循环
        """
        connection_key = f"{shop_id}_{user_id}"
        consecutive_failures = 0

        try:
            while not stop_event.is_set():
                try:
                    # 发送ping消息检查连接
                    start_time = time.time()
                    await websocket.ping()
                    response_time = time.time() - start_time

                    # 重置失败计数
                    consecutive_failures = 0

                    self.logger.debug(f"心跳成功: {shop_id}-{username}, 响应时间: {response_time:.3f}s")

                    # 更新连接状态中的心跳信息
                    status = self.status_manager.get_status(shop_id, user_id)
                    if status and status.state == ConnectionState.CONNECTED:
                        # 可以在ConnectionStatus中添加心跳信息字段
                        pass

                    # 等待下一次心跳
                    await asyncio.sleep(self.heartbeat_config.heartbeat_interval)

                except asyncio.TimeoutError:
                    consecutive_failures += 1
                    self.logger.warning(f"心跳超时: {shop_id}-{username}, 连续失败: {consecutive_failures}")
                    await asyncio.sleep(self.heartbeat_config.heartbeat_timeout)

                except Exception as e:
                    consecutive_failures += 1
                    self.logger.warning(f"心跳失败: {shop_id}-{username}, 错误: {str(e)}, 连续失败: {consecutive_failures}")

                    # 检查是否超过最大失败次数
                    if consecutive_failures >= self.heartbeat_config.max_heartbeat_failures:
                        self.logger.error(f"心跳检查失败次数过多，标记连接为错误状态: {shop_id}-{username}")
                        self.status_manager.update_status(
                            shop_id, user_id, username,
                            ConnectionState.ERROR,
                            f"心跳检查失败: 连续{consecutive_failures}次失败"
                        )
                        break

                    # 等待后重试
                    await asyncio.sleep(self.heartbeat_config.heartbeat_timeout)

        except asyncio.CancelledError:
            self.logger.debug(f"心跳循环被取消: {shop_id}-{username}")
        except Exception as e:
            self.logger.error(f"心跳循环异常: {shop_id}-{username}, 错误: {str(e)}")
        finally:
            # 清理心跳任务记录
            if connection_key in self._heartbeat_tasks:
                del self._heartbeat_tasks[connection_key]
            self.logger.debug(f"心跳循环已结束: {shop_id}-{username}")


    async def _message_loop(self, websocket, shop_id: str, user_id: str, username: str, queue_name: str, stop_event: asyncio.Event):
        """消息接收循环 - 优化版本支持并发处理"""
        try:
            self.logger.info(f"消息循环开始: {shop_id}-{username}")

            async for message in websocket:
                if stop_event.is_set():
                    self.logger.info(f"停止事件已设置，退出消息循环: {shop_id}-{username}")
                    break
                # 创建并发处理任务
                task = asyncio.create_task(
                    self._process_websocket_message_concurrent(
                        message, shop_id, user_id, username, queue_name
                    )
                )

                # 添加到任务跟踪集合
                self.processing_tasks.add(task)
                task.add_done_callback(self.processing_tasks.discard)

        except ws_exceptions.ConnectionClosed as cc:
            self.logger.warning(f"WebSocket连接正常关闭: {shop_id}-{username}, 代码: {cc.code}")
        except ws_exceptions.ConnectionClosedError as cce:
            self.logger.error(f"WebSocket连接异常关闭: {shop_id}-{username}, 错误: {cce}")
        except Exception as e:
            self.logger.error(f"消息循环错误: {shop_id}-{username}, 错误: {str(e)}")

    async def _process_websocket_message_concurrent(
        self, message: str, shop_id: str, user_id: str, username: str, queue_name: str
    ):
        """并发处理WebSocket消息"""
        async with self.message_semaphore:
            try:
                await self._process_websocket_message(message, shop_id, user_id, username, queue_name)
            except Exception as e:
                self.logger.error(f"并发处理消息失败: {e}")

    async def cleanup_processing_tasks(self):
        """清理所有处理任务"""
        if not self.processing_tasks:
            return

        self.logger.info(f"清理 {len(self.processing_tasks)} 个处理任务")
        for task in self.processing_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    self.logger.error(f"清理任务失败: {e}")

        self.processing_tasks.clear()
    
    def request_stop(self) -> None:
        """请求停止WebSocket连接"""
        if self._stop_event:
            self._stop_event.set()
        for event in self._stop_events.values():
            event.set()

    async def stop_all_connections(self):
        """停止所有连接并清理所有任务"""
        try:
            self.logger.info("正在停止所有连接...")

            # 设置全局停止事件
            if self._stop_event:
                self._stop_event.set()
            for event in self._stop_events.values():
                event.set()

            # 停止所有重连任务
            for connection_key, task in list(self._reconnect_tasks.items()):
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=5.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        self.logger.debug(f"任务已取消或超时: {connection_key}")
                    except Exception as e:
                        self.logger.error(f"停止任务时出错: {connection_key}, {e}")
                del self._reconnect_tasks[connection_key]

            # 停止所有心跳任务
            for connection_key, task in list(self._heartbeat_tasks.items()):
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=3.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        self.logger.debug(f"心跳任务已取消或超时: {connection_key}")
                    except Exception as e:
                        self.logger.error(f"停止心跳任务时出错: {connection_key}, {e}")
                del self._heartbeat_tasks[connection_key]

            # 关闭所有WebSocket连接
            for key, ws in list(self._ws_connections.items()):
                try:
                    await self._safe_close_websocket(ws)
                except Exception as e:
                    self.logger.error(f"关闭连接失败: {key}, {e}")
            self._ws_connections.clear()
            self.ws = None

            # 清理所有消息消费者
            try:
                self.logger.debug("消息消费者清理将在应用关闭时由管理器处理")
            except Exception as e:
                self.logger.error(f"清理消息消费者时出错: {e}")

            self.logger.info("所有连接已停止")

        except Exception as e:
            self.logger.error(f"停止所有连接时发生错误: {e}")
    
    async def _setup_message_consumer(self, queue_name: str):
        """
        设置消息消费者和处理器链
        """
        # 延迟导入，避免模块级循环依赖
        from Message import message_consumer_manager, queue_manager, handler_chain
        from Agent.CustomerAgent.agent import CustomerAgent

        try:
            # 检查消费者是否已存在
            existing_consumer = message_consumer_manager.get_consumer(queue_name)
            if existing_consumer and existing_consumer.is_running():
                self.logger.debug(f"消费者 {queue_name} 已在运行，保持存活（重连不重启）")
                return
            if existing_consumer:
                self.logger.info(f"消费者 {queue_name} 未运行，重新创建")
                try:
                    await message_consumer_manager.stop_consumer(queue_name)
                except Exception as e:
                    self.logger.warning(f"停止旧消费者失败: {queue_name}, {e}")
                try:
                    queue_manager.recreate_queue(queue_name)
                except Exception as e:
                    self.logger.warning(f"重新创建队列失败: {queue_name}, {e}")

            # 创建新的消费者（默认 28，相对 API 上限 30 留 2 路余量，见 chat.message_consumer_max_concurrent）
            from config import get_config

            max_ai = int(get_config("chat.message_consumer_max_concurrent", 28) or 28)
            max_ai = max(1, min(max_ai, 50))
            consumer = message_consumer_manager.create_consumer(
                queue_name, max_concurrent=max_ai
            )

            # 添加处理器链（注入AI Bot）
            try:
                from core.di_container import container
                bot = container.get(CustomerAgent)
            except Exception:
                bot = CustomerAgent()
            handlers = handler_chain(use_ai=True, businessHours=self.businessHours, bot=bot)
            for handler in handlers:
                consumer.add_handler(handler)

            await message_consumer_manager.start_consumer(queue_name)
            self.logger.debug(f"消息消费者已启动: {queue_name}")

        except Exception as e:
            self.logger.error(f"设置消息消费者失败: {e}")
            raise
    
    async def _process_websocket_message(self, message: str, shop_id: str, user_id: str, username: str, queue_name: str):
        """
        处理单条WebSocket消息
        """
        # 延迟导入，避免模块级循环依赖
        from Message import put_message

        try:
            # 解析消息
            if not message or not message.strip():
                self.logger.debug(f"收到空消息，跳过处理: {shop_id}-{username}")
                return

            message_data = json.loads(message)
            msg_type = message_data.get("type") if isinstance(message_data, dict) else None
            self.logger.debug(f"收到 WS 消息 type={msg_type}")

            # 转换为PDD消息对象
            try:
                pdd_message = PDDChatMessage(message_data)
            except Exception as pdd_error:
                self.logger.error(f"创建PDD消息对象失败: {shop_id}-{username}, 错误: {pdd_error}")
                return

            # 转换为Context格式
            try:
                context = self._convert_to_context(pdd_message, shop_id, user_id, username)
                if not context:
                    self.logger.debug(f"消息转换失败，跳过处理: {shop_id}-{username}")
                    return
            except Exception as ctx_error:
                self.logger.error(f"转换Context失败: {shop_id}-{username}, 错误: {ctx_error}")
                return

            if context:
                try:
                    from core.human_assist_bus import (
                        emit_buyer_conversation_ended,
                        text_suggests_buyer_left,
                    )
                    from ui.conversation_hub import parse_peer_from_context

                    if text_suggests_buyer_left(context):
                        buid, _ = parse_peer_from_context(context)
                        if buid:
                            emit_buyer_conversation_ended(
                                self.channel_name,
                                str(shop_id),
                                str(user_id),
                                str(username),
                                str(buid),
                            )
                except Exception as e:
                    self.logger.debug(f"买家离开检测/emit 跳过: {e}")

                try:
                    from ui.conversation_hub import get_conversation_hub

                    get_conversation_hub().record_from_context(
                        self.channel_name, shop_id, user_id, username, context
                    )
                except Exception as hub_err:
                    self.logger.debug(f"会话列表登记跳过: {hub_err}")

                # 根据消息类型决定处理方式
                if self._should_process_immediately(context):
                    # 立即处理的消息类型
                    await self._handle_immediate_message(context, shop_id, user_id)
                    self.logger.debug(f"立即处理消息: {context.type}, ID: {pdd_message.msg_id}")
                elif self._should_queue_message(context):
                    # 需要放入队列的消息类型
                    msg_id = await put_message(queue_name, context)
                    self.logger.debug(f"消息已入队: {queue_name}, ID: {msg_id}, 类型: {context.type}")
                else:
                    # 忽略的消息类型
                    self.logger.debug(f"忽略消息: {context.type}, ID: {pdd_message.msg_id}")
            else:
                self.logger.warning("消息转换失败，跳过处理")
                
        except json.JSONDecodeError:
            self.logger.error(f"JSON解析失败: {message}")
        except Exception as e:
            self.logger.error(f"处理WebSocket消息失败: {e}")
    
    def _should_process_immediately(self, context: Context) -> bool:
        """
        判断消息是否需要立即处理（不放入队列）
        
        立即处理的消息类型：
        - 系统状态消息（心跳、连接状态等）
        - 认证消息（登录验证等）
        - 撤回消息（需要及时响应）
        - 系统提示消息
        - 商城客服消息（其他客服发的消息）
        - 转接消息
        """
        immediate_types = {
            ContextType.SYSTEM_STATUS,    # 系统状态
            ContextType.AUTH,             # 认证消息
            ContextType.WITHDRAW,         # 撤回消息
            ContextType.SYSTEM_HINT,      # 系统提示
            ContextType.MALL_CS,          # 商城客服消息
            ContextType.MALL_SYSTEM_MSG,  # 含快捷退款卡过期(type=90)等
            ContextType.TRANSFER          # 转接消息
        }
        
        return context.type in immediate_types
    
    def _should_queue_message(self, context: Context) -> bool:
        """
        判断消息是否需要放入队列处理
        
        放入队列的消息类型：
        - 用户文本消息（需要AI分析和回复）
        - 图片消息（需要识别和处理）
        - 视频消息（需要分析处理）
        - 表情消息（需要智能回复）
        - 商品咨询（需要详细业务处理）
        - 订单信息（需要查询和处理）
        - 商品卡片（需要业务逻辑处理）
        """
        queue_types = {
            ContextType.TEXT,             # 文本消息
            ContextType.IMAGE,            # 图片消息
            ContextType.VIDEO,            # 视频消息
            ContextType.EMOTION,          # 表情消息
            ContextType.GOODS_INQUIRY,    # 商品咨询
            ContextType.ORDER_INFO,       # 订单信息
            ContextType.GOODS_CARD,       # 商品卡片
            ContextType.GOODS_SPEC,       # 商品规格
        }
        
        return context.type in queue_types
    
    async def _handle_immediate_message(self, context: Context, shop_id: str, user_id: str):
        """
        立即处理消息
        """
        username = context.kwargs.username
        recipient_uid = context.kwargs.from_uid
        try:
            from Channel.pinduoduo.utils.API.send_message import SendMessage
            send_message = SendMessage(shop_id, user_id)
            if context.type == ContextType.AUTH:
                # 认证消息处理
                auth_info = context.content
                if isinstance(auth_info, dict):
                    result = auth_info.get('result')
                    if result == 'ok':
                        self.logger.info(f"{username}认证成功")
                    else:
                        self.logger.warning(
                            f"{username} auth result: fail，关闭连接触发重连"
                        )
                        connection_key = f"{shop_id}_{user_id}"
                        ws = self._ws_connections.get(connection_key)
                        if ws:
                            await self._safe_close_websocket(ws)
                        
            elif context.type == ContextType.WITHDRAW:
                # 撤回消息处理
                self.logger.info(f"收到撤回消息: {context.content}")
                send_message.send_text(recipient_uid,"[玫瑰]")

            elif context.type == ContextType.SYSTEM_STATUS:
                # 系统状态消息
                self.logger.debug(f"系统状态消息: {context.content}")
                
            elif context.type == ContextType.SYSTEM_HINT:
                # 系统提示消息
                self.logger.info(f"系统提示: {context.content}")
                
            elif context.type == ContextType.MALL_CS:
                await self._handle_mall_cs_message(
                    context, shop_id, user_id, send_message
                )
                
            elif context.type == ContextType.SYSTEM_BIZ:
                # 系统业务消息
                self.logger.info(f"系统业务消息: {context.content}")
                
            elif context.type == ContextType.MALL_SYSTEM_MSG:
                await self._handle_mall_system_msg(context, shop_id, user_id, send_message)
                
            elif context.type == ContextType.TRANSFER:
                # 转接消息
                self.logger.info(f"转接消息: {context.content}")
                send_message.send_text(recipient_uid,"[玫瑰]")
                
        except Exception as e:
            self.logger.error(f"立即处理消息失败: {e}")

    async def _notify_refund_card_unusable(
        self,
        shop_id: str,
        buyer_uid: str,
        send_message: Any,
        *,
        order_sn: Optional[str] = None,
        reason: str = "expired",
    ) -> None:
        from utils.session_order_cache import (
            get_recent_order,
            mark_refund_card_unusable,
        )

        uid = str(buyer_uid)
        sn = (order_sn or "").strip() or get_recent_order(str(shop_id), uid)
        if sn:
            mark_refund_card_unusable(str(shop_id), uid, sn)
        notice = config.get(
            "chat.after_sales_apply_merchant_window_expired_notice"
        ) or config.get(
            "chat.after_sales_apply_card_expired_notice",
            "亲，该订单商家代申请退款的时效已过或次数已满，快捷退款卡片无法使用。"
            "请您打开订单详情点击「申请售后」自行提交，或回复「人工」为您处理~",
        )
        if notice:
            await asyncio.to_thread(send_message.send_text, uid, str(notice))

    async def _handle_mall_cs_message(
        self,
        context: Context,
        shop_id: str,
        user_id: str,
        send_message: Any,
    ) -> None:
        """本店客服消息；解析 type=19 快捷退款卡下行（含是否已过期）。"""
        payload = _context_struct_payload(context)
        if payload.get("event") != "ask_refund_card_push":
            if context.content:
                self.logger.debug(f"收到客服消息: {context.content}")
            return

        from Channel.pinduoduo.utils.API.chat_orders import refund_card_push_expired

        buyer_uid = payload.get("to_uid")
        order_sn = payload.get("order_sn")
        expired = refund_card_push_expired(
            {"expire_text": payload.get("state_expire_text")},
            {
                "expire_text": payload.get("mstate_expire_text"),
                "status": payload.get("mstate_status"),
            },
        )
        mstate_status = payload.get("mstate_status")
        from utils.merchant_refund_apply_record import (
            gate_notice,
            get_apply_counts,
            mark_apply_expired,
            update_apply_from_card_push,
            RefundApplyGate,
        )

        valid_time_unix: Optional[int] = None
        try:
            vt_raw = payload.get("valid_time")
            if vt_raw is not None:
                valid_time_unix = int(float(vt_raw))
        except (TypeError, ValueError):
            pass

        if buyer_uid and order_sn:
            update_apply_from_card_push(
                str(shop_id),
                str(buyer_uid),
                str(order_sn),
                card_msg_id=str(payload.get("card_msg_id") or "") or None,
                valid_time_unix=valid_time_unix,
                card_expired=expired,
            )
            counts = get_apply_counts(str(shop_id), str(buyer_uid), str(order_sn))
            self.logger.info(
                f"代申请记录已更新 order_sn={order_sn} expired={expired} "
                f"valid_time={valid_time_unix} 本单成功={counts.get('order_total', 0)}"
            )

        self.logger.info(
            f"快捷退款卡下行 order_sn={order_sn} buyer={buyer_uid} "
            f"state_expire={payload.get('state_expire_text')!r} "
            f"mstate_status={mstate_status} mstate_expire={payload.get('mstate_expire_text')!r} "
            f"valid_time={payload.get('valid_time')} expired={expired}"
        )
        if not buyer_uid:
            return
        if expired:
            self.logger.warning(
                f"商家代申请退款窗口已失效 order_sn={order_sn} buyer={buyer_uid} "
                f"(mstate.status={payload.get('mstate_status')} 且 expire_text=已过期，"
                f"通常为同单重复代申请或超时)"
            )
            from utils.session_order_cache import mark_refund_card_unusable

            mark_refund_card_unusable(str(shop_id), str(buyer_uid), str(order_sn))
            notice = gate_notice(RefundApplyGate.EXPIRED_NOTICE)
            await asyncio.to_thread(send_message.send_text, str(buyer_uid), notice)
            return
        cfg_hours = int(config.get("chat.after_sales_apply_card_valid_hours", 48) or 48)
        remain_h: Optional[float] = None
        try:
            vt = float(payload.get("valid_time") or 0)
            if vt > 0:
                remain_h = max(0.0, (vt - time.time()) / 3600.0)
        except (TypeError, ValueError):
            pass
        if remain_h is not None:
            self.logger.info(
                f"快捷退款卡有效 order_sn={order_sn} "
                f"(mstate.status={mstate_status} 配置截止={cfg_hours}h "
                f"平台valid_time剩余={remain_h:.1f}h)"
            )
        else:
            self.logger.info(
                f"快捷退款卡有效 order_sn={order_sn} "
                f"(mstate.status={mstate_status} 配置截止={cfg_hours}h)"
            )
        follow = config.get("chat.after_sales_apply_follow_text") or ""
        if follow:
            await asyncio.to_thread(
                send_message.send_text, str(buyer_uid), str(follow)
            )

    async def _handle_mall_system_msg(
        self,
        context: Context,
        shop_id: str,
        user_id: str,
        send_message: Any,
    ) -> None:
        """商城系统消息：快捷退款卡过期/确认等平台侧通知。"""
        payload = _context_struct_payload(context)
        event = payload.get("event")
        if event == "refund_card_confirmed":
            self.logger.info(
                f"买家已确认快捷退款卡 shop={shop_id} buyer={payload.get('user_id')} "
                f"card_msg_id={payload.get('msg_id')}"
            )
            return
        if event != "refund_card_expired":
            if payload:
                from utils.log_redact import redact_log_payload

                self.logger.debug(
                    f"商城系统消息: {redact_log_payload(payload)}"
                )
            return

        buyer_uid = payload.get("user_id")
        card_msg_id = payload.get("msg_id")
        self.logger.warning(
            f"快捷退款卡已过期 shop={shop_id} buyer={buyer_uid} card_msg_id={card_msg_id}"
        )
        if not buyer_uid:
            return
        from database.db_manager import db_manager
        from utils.merchant_refund_apply_record import (
            gate_notice,
            mark_apply_expired,
            RefundApplyGate,
        )

        row = (
            db_manager.get_refund_apply_by_card_msg_id(str(shop_id), str(card_msg_id))
            if card_msg_id
            else None
        )
        already_expired = row and (row.get("status") or "") == "expired"
        sn = (row or {}).get("order_sn") or ""
        if sn:
            mark_apply_expired(
                str(shop_id), sn, buyer_uid=str(buyer_uid), card_msg_id=card_msg_id
            )
        elif card_msg_id:
            mark_apply_expired(
                str(shop_id),
                "",
                buyer_uid=str(buyer_uid),
                card_msg_id=card_msg_id,
            )
        if already_expired:
            return
        notice = gate_notice(RefundApplyGate.EXPIRED_NOTICE)
        await asyncio.to_thread(send_message.send_text, str(buyer_uid), notice)

    async def _cleanup_reconnect_tasks(self, connection_key: Optional[str] = None):
        """清理重连任务；传 connection_key 时仅清理单账号。"""
        try:
            keys = [connection_key] if connection_key else list(self._reconnect_tasks.keys())
            for key in keys:
                task = self._reconnect_tasks.get(key)
                if task is None:
                    continue
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=5.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass
                    except asyncio.InvalidStateError:
                        # 任务在不同的的事件循环中，直接忽略
                        self.logger.debug(f"重连任务在不同的的事件循环中: {key}")
                    except Exception as e:
                        self.logger.error(f"清理重连任务失败: {key}, {e}")
                self._reconnect_tasks.pop(key, None)
        except Exception as e:
            self.logger.error(f"清理重连任务列表失败: {e}")

    async def _cleanup_heartbeat_tasks(self, connection_key: Optional[str] = None):
        """清理心跳任务；传 connection_key 时仅清理单账号。"""
        try:
            keys = [connection_key] if connection_key else list(self._heartbeat_tasks.keys())
            for key in keys:
                task = self._heartbeat_tasks.get(key)
                if task is None:
                    continue
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=3.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass
                    except asyncio.InvalidStateError:
                        # 任务在不同的的事件循环中，直接忽略
                        self.logger.debug(f"心跳任务在不同的的事件循环中: {key}")
                    except Exception as e:
                        self.logger.error(f"清理心跳任务失败: {key}, {e}")
                self._heartbeat_tasks.pop(key, None)
        except Exception as e:
            self.logger.error(f"清理心跳任务列表失败: {e}")

    async def _cleanup_resources(
        self,
        queue_name: str,
        connection_key: Optional[str] = None,
        *,
        keep_consumer: bool = False,
    ):
        """
        清理资源 - 优化版本支持完整资源管理
        """
        # 延迟导入，避免模块级循环依赖
        from Message import message_consumer_manager

        try:
            # 清理处理任务
            await self.cleanup_processing_tasks()

            # 清理重连任务
            await self._cleanup_reconnect_tasks(connection_key)

            # 清理心跳任务
            await self._cleanup_heartbeat_tasks(connection_key)

            # 清理连接引用（单账号）
            if connection_key:
                ws = self._ws_connections.pop(connection_key, None)
                if ws:
                    await self._safe_close_websocket(ws)
                self._stop_events.pop(connection_key, None)
            else:
                # 全量清理场景（例如应用关闭）
                await self.resource_manager.cleanup_all()
                self._ws_connections.clear()
                self._stop_events.clear()

            # 停止消息消费者（重连期间默认保持消费者存活）
            try:
                should_stop_consumer = not keep_consumer
                if connection_key and not keep_consumer:
                    # 同店铺仍有其他账号连接时不停止共享消费者
                    shop_prefix = f"{queue_name.replace('pdd_', '')}_"
                    should_stop_consumer = not any(
                        k.startswith(shop_prefix) for k in self._ws_connections.keys()
                    )
                if should_stop_consumer:
                    await message_consumer_manager.stop_consumer(queue_name)
                    self.logger.debug(f"已停止消息消费者: {queue_name}")
            except asyncio.InvalidStateError:
                self.logger.debug(f"消息消费者已在其他事件循环中停止: {queue_name}")
            except Exception as e:
                self.logger.warning(f"停止消息消费者失败: {queue_name}, {e}")

            # 清理WebSocket连接引用
            self.ws = None

        except Exception as e:
            self.logger.error(f"清理资源失败: {e}")

    def _convert_to_context(self, pdd_message: PDDChatMessage, shop_id: str, user_id: str, username: str) -> Optional[Context]:
        """
        将拼多多消息转换为Context格式

        Args:
            pdd_message: 拼多多消息对象
            shop_id: 店铺ID
            user_id: 用户ID
            username: 用户名

        Returns:
            Context对象或None
        """
        try:
            # 获取店铺信息
            shop_info = db_manager.get_shop(self.channel_name, shop_id)
            shop_name = shop_info.get("shop_name", "")

            # 直接从pdd_message中获取Context类型
            context_type = pdd_message.user_msg_type

            # 处理content字段，确保它是字符串类型
            content = pdd_message.content
            if isinstance(content, dict):
                # 如果content是字典（如认证消息），转换为JSON字符串
                import json
                content = json.dumps(content, ensure_ascii=False)
            elif content is None:
                content = ""
            else:
                content = str(content)

            # 使用新的优化方式创建Context对象
            context = Context.create_pinduoduo_context(
                content=content,
                msg_id=str(pdd_message.msg_id) if pdd_message.msg_id is not None else "",
                from_user=str(pdd_message.from_user) if pdd_message.from_user is not None else "",
                from_uid=str(pdd_message.from_uid) if pdd_message.from_uid is not None else "",
                to_user=str(pdd_message.to_user) if pdd_message.to_user is not None else "",
                to_uid=str(pdd_message.to_uid) if pdd_message.to_uid is not None else "",
                nickname=str(pdd_message.nickname) if pdd_message.nickname is not None else "",
                timestamp=pdd_message.timestamp,
                user_msg_type=pdd_message.user_msg_type,
                shop_id=str(shop_id),
                user_id=str(user_id),
                username=str(username),
                shop_name=str(shop_name),
                raw_data=pdd_message.raw_data,
                channel_type=ChannelType.PINDUODUO
            )

            return context

        except Exception as e:
            self.logger.error(f"转换消息格式时发生错误: {e}")
            return None

    def _is_ws_closed(self, ws: Any) -> bool:
        try:
            closed = getattr(ws, "closed", None)
            if isinstance(closed, bool):
                return closed
            return False
        except Exception:
            return False

    async def _safe_close_websocket(self, ws: Any):
        try:
            close_fn = getattr(ws, "close", None)
            if close_fn:
                result = close_fn()
                if asyncio.iscoroutine(result):
                    await result
        except Exception as e:
            self.logger.debug(f"关闭WebSocket失败: {e}")

# ============================================================================
# 便捷的全局函数 - 供外部模块直接调用
# ============================================================================

def get_pdd_connection_status() -> List[ConnectionStatus]:
    """获取所有拼多多连接状态 - 全局便捷函数"""
    from core.di_container import container
    sm = container.get(ConnectionStatusManager)
    return sm.get_all_status()

def get_pdd_connected_count() -> int:
    """获取当前拼多多连接数 - 全局便捷函数"""
    from core.di_container import container
    sm = container.get(ConnectionStatusManager)
    return sm.get_connected_count()

def get_pdd_connection_summary() -> Dict[str, int]:
    """获取拼多多连接状态汇总 - 全局便捷函数"""
    from core.di_container import container
    sm = container.get(ConnectionStatusManager)
    all_status = sm.get_all_status()
    summary = {
        "total": len(all_status),
        "connected": 0,
        "connecting": 0,
        "reconnecting": 0,
        "error": 0,
        "disconnected": 0
    }

    for status in all_status:
        summary[status.state.value] += 1

    return summary

def get_pdd_heartbeat_status_all() -> Dict[str, Dict]:
    """
    获取所有拼多多连接的状态信息 - 全局便捷函数

    注意：心跳任务的运行状态需要从具体的 PDDChannel 实例获取，
    此函数通过 ConnectionStatusManager 返回连接级别的基础状态。
    """
    from core.di_container import container
    sm = container.get(ConnectionStatusManager)
    heartbeat_status = {}

    all_status = sm.get_all_status()
    for status in all_status:
        connection_key = f"{status.shop_id}_{status.user_id}"
        heartbeat_status[connection_key] = {
            "connection_key": connection_key,
            "connection_state": status.state.value if status else None,
            "last_error": status.last_error if status else None,
            "error_count": status.error_count if status else 0,
            "reconnect_count": status.reconnect_count if status else 0,
            # 注意：heartbeat_running 等运行时信息需要从具体 PDDChannel 实例获取
            "heartbeat_running": False,
        }

    return heartbeat_status
