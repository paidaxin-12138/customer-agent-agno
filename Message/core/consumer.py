"""
简化的消息消费者实现
移除复杂的用户隔离机制，保持核心功能
"""

import asyncio
from typing import Dict, List

from utils.buyer_lock_registry import BuyerLockRegistry
from utils.logger_loguru import get_logger
from bridge.context import Context
from .queue import queue_manager
from .handlers import MessageHandler
from ..models.queue_models import MessageWrapper


logger = get_logger(__name__)


class MessageConsumer:
    """消息消费者 - 有界 worker 池，避免 create_task 无限堆积"""

    def __init__(self, queue_name: str, max_concurrent: int = 28):
        self.queue_name = queue_name
        self.max_concurrent = max(1, max_concurrent)
        self.handlers: List[MessageHandler] = []
        self.running = False
        self.consumer_task = None
        self._worker_tasks: List[asyncio.Task] = []
        self.logger = get_logger(f"Consumer.{queue_name}")
        self._buyer_locks = BuyerLockRegistry(max_keys=5000)

    def add_handler(self, handler: MessageHandler):
        """添加处理器"""
        self.handlers.append(handler)
        self.logger.debug(f"Added handler: {handler.__class__.__name__}")

    def is_running(self) -> bool:
        """检查消费者是否正在运行"""
        return self.running

    async def start(self):
        """启动消费者"""
        if self.running:
            self.logger.warning(f"Consumer {self.queue_name} is already running")
            return

        self.running = True
        self.consumer_task = asyncio.create_task(self._consume_loop())
        self.logger.info(f"Consumer {self.queue_name} started ({self.max_concurrent} workers)")

    async def _consume_loop(self):
        """启动固定数量 worker，从队列取消息并 await 处理（有界并发）"""
        self._worker_tasks = [
            asyncio.create_task(self._worker_loop(i)) for i in range(self.max_concurrent)
        ]
        try:
            await asyncio.gather(*self._worker_tasks)
        except asyncio.CancelledError:
            pass
        finally:
            self.logger.info(f"Consumer {self.queue_name} stopped")

    async def _worker_loop(self, worker_id: int):
        queue = queue_manager.get_or_create_queue(self.queue_name)
        while self.running:
            try:
                wrapper = await queue.get(timeout=1.0)
            except Exception as e:
                self.logger.error(f"Consumer worker {worker_id} dequeue error: {e}")
                await asyncio.sleep(0.1)
                continue
            if not wrapper:
                continue
            try:
                await self._process_message(wrapper)
            except Exception as e:
                self.logger.error(
                    f"Consumer worker {worker_id} process error: {e}"
                )

    async def stop(self):
        """停止消费者并等待在途消息处理完成"""
        self.running = False

        task = getattr(self, "consumer_task", None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self.consumer_task = None

        for wt in self._worker_tasks:
            if not wt.done():
                wt.cancel()
        if self._worker_tasks:
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        self._worker_tasks.clear()

    def _record_process_failure(
        self,
        metadata: Dict,
        *,
        handler_name: str = "",
        error: Exception | None = None,
    ) -> None:
        try:
            from core.ops_telemetry import record_message_failed

            record_message_failed(
                queue_name=self.queue_name,
                handler_name=handler_name,
                error=error,
                metadata=metadata,
            )
        except Exception as te:
            self.logger.debug(f"record_message_failed: {te}")

    async def _process_message(self, wrapper: MessageWrapper):
        """处理单个消息"""
        user_key = self._extract_user_id(wrapper.context)
        lock = self._buyer_locks.lock_for(user_key)
        async with lock:
            metadata: Dict = {}
            try:
                processed = False
                metadata = wrapper.to_metadata()
                try:
                    kwargs = getattr(wrapper.context, "kwargs", None)
                    if kwargs:
                        metadata["shop_id"] = getattr(kwargs, "shop_id", None)
                        metadata["user_id"] = getattr(kwargs, "user_id", None)
                        metadata["from_uid"] = getattr(kwargs, "from_uid", None)
                        metadata["username"] = getattr(kwargs, "username", None)
                        ct = getattr(wrapper.context, "channel_type", None)
                        metadata["channel_name"] = (
                            ct.value if ct is not None and hasattr(ct, "value") else "pinduoduo"
                        )
                except Exception as e:
                    self.logger.debug(f"metadata enrich skipped: {e}")
                metadata["user_key"] = user_key

                watchdog_epoch = 0
                try:
                    from Message.handlers.ai_reply_watchdog import start_inbound_watchdog

                    watchdog_epoch = await start_inbound_watchdog(
                        wrapper.context,
                        metadata,
                        str(wrapper.context.content or ""),
                    )
                    metadata["_watchdog_epoch"] = watchdog_epoch
                except Exception as wd_err:
                    self.logger.warning(f"inbound watchdog 启动失败: {wd_err}")

                for handler in self.handlers:
                    try:
                        if handler.can_handle(wrapper.context):
                            success = await handler.handle(wrapper.context, metadata)
                            if success:
                                processed = True
                                try:
                                    from core.app_metrics import record_message_processed

                                    record_message_processed()
                                except Exception:
                                    pass
                                self.logger.debug(
                                    f"Message {wrapper.message_id} handled by {handler.__class__.__name__}"
                                )
                                break
                    except Exception as e:
                        hname = handler.__class__.__name__
                        self.logger.error(f"Handler {hname} error: {e}")
                        try:
                            from core.ops_telemetry import record_handler_error

                            record_handler_error(hname, e, metadata)
                        except Exception as te:
                            self.logger.debug(f"record_handler_error: {te}")
                        try:
                            await handler.on_error(wrapper.context, e)
                        except Exception as oe:
                            self.logger.debug(f"on_error callback: {oe}")
                        continue

                if not processed and not metadata.get("_outbound_comfort_sent"):
                    self.logger.warning(
                        f"Message {wrapper.message_id} not processed by any handler"
                    )
                    try:
                        from Message.handlers.fallback_reply import (
                            try_send_unhandled_fallback,
                        )

                        if await try_send_unhandled_fallback(
                            wrapper.context, metadata
                        ):
                            processed = True
                        else:
                            try:
                                from core.ops_telemetry import record_unhandled_message

                                ct = getattr(wrapper.context.type, "value", wrapper.context.type)
                                record_unhandled_message(metadata, context_type=str(ct))
                            except Exception as ue:
                                self.logger.debug(f"record_unhandled_message: {ue}")
                    except Exception as fb_err:
                        self.logger.warning(f"未处理消息安抚失败: {fb_err}")

                if not processed:
                    self._record_process_failure(metadata)

            except Exception as e:
                self.logger.error(f"Failed to process message {wrapper.message_id}: {e}")
                self._record_process_failure(metadata, error=e)

    def _extract_user_id(self, context: Context) -> str:
        """提取用户ID"""
        try:
            from_uid = context.kwargs.from_uid if hasattr(context, "kwargs") else None
            channel = context.channel_type

            if from_uid is None:
                from_uid = "unknown"
            if channel is None:
                channel = "unknown"

            if hasattr(channel, "value"):
                channel_str = str(channel.value)
            else:
                channel_str = str(channel)

            return f"{channel_str}_{from_uid}"
        except Exception as e:
            self.logger.error(f"Failed to extract user ID: {e}")
            return "unknown_unknown"


class MessageConsumerManager:
    """消息消费者管理器"""

    def __init__(self):
        self._consumers: Dict[str, MessageConsumer] = {}
        self.logger = get_logger("ConsumerManager")

    def create_consumer(self, queue_name: str, max_concurrent: int = 28) -> MessageConsumer:
        """创建消费者"""
        if queue_name in self._consumers:
            self.logger.warning(f"Consumer {queue_name} already exists")
            return self._consumers[queue_name]

        consumer = MessageConsumer(queue_name, max_concurrent)
        self._consumers[queue_name] = consumer
        self.logger.info(f"Created consumer: {queue_name}")
        return consumer

    def get_consumer(self, queue_name: str) -> MessageConsumer:
        """获取消费者"""
        return self._consumers.get(queue_name)

    async def start_consumer(self, queue_name: str):
        """启动消费者"""
        consumer = self.get_consumer(queue_name)
        if consumer:
            await consumer.start()
        else:
            self.logger.error(f"Consumer {queue_name} not found")

    async def stop_consumer(self, queue_name: str):
        """停止消费者"""
        consumer = self.get_consumer(queue_name)
        if consumer:
            await consumer.stop()
        else:
            self.logger.error(f"Consumer {queue_name} not found")

    def list_consumers(self) -> List[str]:
        """列出所有消费者"""
        return list(self._consumers.keys())

    async def stop_all(self):
        """停止所有消费者"""
        for consumer in self._consumers.values():
            await consumer.stop()
        self.logger.info("All consumers stopped")


message_consumer_manager = MessageConsumerManager()
