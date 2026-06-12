# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
简化的消息消费者实现
移除复杂的用户隔离机制，保持核心功能
"""

import asyncio
import time
from typing import Dict, List

from utils.buyer_lock_registry import BuyerLockRegistry
from utils.logger_loguru import get_logger
from config import get_config
from bridge.context import Context
from .queue import queue_manager
from .handlers import MessageHandler
from ..models.queue_models import MessageWrapper


logger = get_logger(__name__)

_AI_CHAIN_HANDLERS = frozenset({"AIReplyHandler", "CatchAllHandler"})
_BUSINESS_CHAIN_HANDLERS = frozenset(
    {
        "AddressChangeHandler",
        "OrderLogisticsHandler",
        "ImageVideoHumanHandler",
        "AfterSalesApplyHandler",
        "BuyerEmotionHandler",
        "KeywordDetectionHandler",
    }
)


def _invoke_can_handle(handler: MessageHandler, context: Context, metadata: Dict) -> bool:
    """兼容旧 Handler 仅声明 can_handle(context) 的签名。"""
    try:
        return handler.can_handle(context, metadata)
    except TypeError:
        return handler.can_handle(context)


def _dismiss_watchdog_if_handler_resolved_without_outbound(
    context: Context,
    metadata: Dict,
    *,
    processed: bool,
) -> None:
    """业务 Handler 已消费消息但未出站时，取消误触发的 inbound watchdog。"""
    if not processed:
        return
    if not int(metadata.get("_watchdog_epoch") or 0):
        return
    if metadata.get("_outbound_comfort_sent"):
        return
    if not metadata.get("_handler_resolved_without_outbound"):
        return
    try:
        from Message.handlers.channel_send import notify_outbound_from_metadata

        notify_outbound_from_metadata(context, metadata)
        metadata["_watchdog_resolved_without_outbound"] = True
    except Exception as exc:
        logger.debug("watchdog resolve without outbound: {}", exc)


class MessageConsumer:
    """消息消费者 - 有界 worker 池，避免 create_task 无限堆积"""

    def __init__(self, queue_name: str, max_concurrent: int = 16):
        self.queue_name = queue_name
        self.max_concurrent = max(1, max_concurrent)
        self.handlers: List[MessageHandler] = []
        self.running = False
        self.consumer_task = None
        self._worker_tasks: List[asyncio.Task] = []
        self.logger = get_logger(f"Consumer.{queue_name}")
        self._buyer_locks = BuyerLockRegistry(max_keys=5000)
        self._last_dead_letter_replay = 0.0

    def _dead_letter_replay_interval_sec(self) -> float:
        try:
            v = float(get_config("chat.dead_letter_replay_interval_sec", 60) or 60)
            return max(10.0, min(v, 600.0))
        except (TypeError, ValueError):
            return 60.0

    async def _maybe_replay_dead_letters(self, worker_id: int) -> None:
        if worker_id != 0:
            return
        if not bool(get_config("chat.dead_letter_periodic_replay_enabled", True)):
            return
        interval = self._dead_letter_replay_interval_sec()
        now = time.monotonic()
        if now - self._last_dead_letter_replay < interval:
            return
        self._last_dead_letter_replay = now
        try:
            from Message.dead_letter import replay_pending_for_queue

            replayed = await replay_pending_for_queue(self.queue_name)
            if replayed:
                self.logger.info(
                    "idle dead-letter 重放 {} 条 queue={}",
                    replayed,
                    self.queue_name,
                )
        except Exception as exc:
            self.logger.debug("idle dead-letter 重放跳过: {}", exc)

    def add_handler(self, handler: MessageHandler):
        """添加处理器"""
        self.handlers.append(handler)
        self.logger.debug(f"Added handler: {handler.__class__.__name__}")

    def clear_handlers(self) -> None:
        """清空处理器链（重连重建消费者前调用，避免重复挂载）。"""
        self.handlers.clear()

    def is_running(self) -> bool:
        """检查消费者是否正在运行"""
        return self.running

    async def start(self):
        """启动消费者"""
        if self.running:
            self.logger.warning(f"Consumer {self.queue_name} is already running")
            return

        self.running = True
        self._owner_loop = asyncio.get_running_loop()
        self.consumer_task = asyncio.create_task(self._consume_loop())
        if get_config("chat.queue_force_enqueue", False):
            self.logger.warning(
                "chat.queue_force_enqueue enabled: full queue will drop oldest messages"
            )
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
                await self._maybe_replay_dead_letters(worker_id)
                continue
            try:
                await self._process_message(wrapper)
            except Exception as e:
                self.logger.error(
                    f"Consumer worker {worker_id} process error: {e}"
                )

    async def stop(self):
        """停止消费者：先停接新消息， drain 队列，等待在途 worker 结束。"""
        self.running = False

        try:
            from core.turn_abort import turn_abort_registry

            aborted = turn_abort_registry.abort_all_active("consumer_stop")
            if aborted:
                self.logger.info(
                    "Consumer {} stop: aborted {} in-flight turn(s)",
                    self.queue_name,
                    aborted,
                )
        except Exception as exc:
            self.logger.debug("consumer stop turn abort skipped: {}", exc)

        try:
            queue = queue_manager.get_queue(self.queue_name)
            if queue:
                drained = queue.drain_to_dead_letter("consumer_stop")
                if drained:
                    self.logger.info(
                        "Consumer {} stop: drained {} queued message(s) to dead-letter",
                        self.queue_name,
                        drained,
                    )
        except Exception as exc:
            self.logger.debug("consumer stop drain skipped: {}", exc)

        if self._worker_tasks:
            _done, pending = await asyncio.wait(
                self._worker_tasks,
                timeout=5.0,
                return_when=asyncio.ALL_COMPLETED,
            )
            for wt in pending:
                wt.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        task = getattr(self, "consumer_task", None)
        if task is not None:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self.consumer_task = None

        self._worker_tasks.clear()
        self._buyer_locks.clear()
        self.logger.debug(f"Consumer {self.queue_name} workers and locks cleared")

    def _persist_process_failure_dead_letter(self, context: Context) -> None:
        try:
            from Message.dead_letter import persist_dead_letter

            persist_dead_letter(
                self.queue_name, context, reason="process_failure"
            )
        except Exception as exc:
            self.logger.debug("process_failure dead-letter: {}", exc)

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
        processed = False
        metadata: Dict = {}
        ctx_type = getattr(wrapper.context.type, "value", wrapper.context.type)
        self.logger.info(
            "[DEQUEUE] queue={} msg_id={} type={} user_key={}",
            self.queue_name,
            wrapper.message_id,
            ctx_type,
            user_key,
        )
        async with self._buyer_locks.hold(user_key):
            try:
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
                try:
                    from database.session_store import prime_metadata_session

                    await asyncio.to_thread(
                        prime_metadata_session, metadata, wrapper.context
                    )
                except Exception as prime_err:
                    self.logger.warning(
                        "prime_metadata_session 失败，责任链将回退查 DB: {}",
                        prime_err,
                    )
                try:
                    ku = getattr(wrapper.context, "kwargs", None)
                    raw = getattr(ku, "raw_data", None) if ku else None
                    if isinstance(raw, dict) and raw.get("_transfer_takeover"):
                        metadata["transfer_takeover"] = True
                except Exception:
                    pass

                try:
                    from Agent.CustomerAgent.conversation_memory import (
                        prime_session_stage_on_context,
                    )

                    await asyncio.to_thread(
                        prime_session_stage_on_context, wrapper.context, metadata
                    )
                except Exception as stage_err:
                    self.logger.debug(f"prime_session_stage: {stage_err}")

                try:
                    from utils.intent_stage_reset import try_intent_stage_reset

                    msg_text = (
                        wrapper.context.content
                        if isinstance(wrapper.context.content, str)
                        else str(wrapper.context.content or "")
                    )
                    reset = await asyncio.to_thread(
                        try_intent_stage_reset,
                        wrapper.context,
                        metadata,
                        message_text=msg_text,
                    )
                    if reset:
                        await asyncio.to_thread(
                            prime_session_stage_on_context,
                            wrapper.context,
                            metadata,
                        )
                except Exception as reset_err:
                    self.logger.debug(f"intent_stage_reset: {reset_err}")

                try:
                    from utils.inbound_transfer_gate import (
                        should_block_handler_until_transfer,
                    )

                    if should_block_handler_until_transfer(
                        wrapper.context, metadata
                    ):
                        self.logger.info(
                            "[GATE] 接待号未转接入线，跳过责任链 queue={} buyer={}",
                            self.queue_name,
                            user_key,
                        )
                        processed = True
                        metadata["inbound_transfer_gated"] = True
                        return
                except Exception as gate_err:
                    self.logger.debug("inbound_transfer_gate: {}", gate_err)

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
                        if _invoke_can_handle(handler, wrapper.context, metadata):
                            success = await handler.handle(wrapper.context, metadata)
                            if success:
                                processed = True
                                hname = handler.__class__.__name__
                                metadata["handled_by"] = hname
                                metadata["handler_already_processed"] = (
                                    hname not in _AI_CHAIN_HANDLERS
                                )
                                try:
                                    from core.app_metrics import record_message_processed

                                    record_message_processed()
                                except Exception:
                                    pass
                                extra = (
                                    " transfer_takeover"
                                    if metadata.get("transfer_takeover")
                                    else ""
                                )
                                self.logger.info(
                                    "[HANDLED] queue={} msg_id={} handled_by={}{}",
                                    self.queue_name,
                                    wrapper.message_id,
                                    hname,
                                    extra,
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
                        if hname in _BUSINESS_CHAIN_HANDLERS:
                            self.logger.warning(
                                "业务 Handler {} 异常，继续责任链: {}",
                                hname,
                                e,
                            )
                        continue

                _dismiss_watchdog_if_handler_resolved_without_outbound(
                    wrapper.context, metadata, processed=processed
                )

                if not processed and metadata.get("_outbound_comfort_sent"):
                    processed = True
                    metadata.setdefault("handled_by", "outbound_sent")

                if not processed and not metadata.get("_outbound_comfort_sent"):
                    try:
                        from Agent.CustomerAgent.conversation_memory import (
                            get_current_stage,
                        )

                        stage_now = get_current_stage(wrapper.context, metadata)
                    except Exception:
                        stage_now = "?"
                    self.logger.warning(
                        "Message {} 未被任何 handler 处理 stage={} type={}，尝试 fallback_reply",
                        wrapper.message_id,
                        stage_now,
                        getattr(wrapper.context.type, "value", wrapper.context.type),
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
                    await asyncio.to_thread(
                        self._persist_process_failure_dead_letter,
                        wrapper.context,
                    )

            except Exception as e:
                self.logger.error(f"Failed to process message {wrapper.message_id}: {e}")
                self._record_process_failure(metadata, error=e)
                await asyncio.to_thread(
                    self._persist_process_failure_dead_letter,
                    wrapper.context,
                )
            finally:
                handled_by = metadata.get("handled_by", "")
                self.logger.info(
                    "[DONE] queue={} msg_id={} processed={} handled_by={} user_key={}",
                    self.queue_name,
                    wrapper.message_id,
                    processed,
                    handled_by or "-",
                    user_key,
                )

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

    def create_consumer(self, queue_name: str, max_concurrent: int = 16) -> MessageConsumer:
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

    async def stop_consumer(self, queue_name: str, *, remove: bool = True):
        """停止消费者；remove=True 时从注册表移除，便于重连后创建新实例。"""
        consumer = self.get_consumer(queue_name)
        if consumer:
            await consumer.stop()
            if remove:
                self._consumers.pop(queue_name, None)
        else:
            self.logger.error(f"Consumer {queue_name} not found")

    def detach_all(self) -> None:
        """仅清空注册表（AutoReply 线程已在其 event loop 内停止消费者后调用）。"""
        self._consumers.clear()
        self.logger.info("All consumers detached from registry")

    def list_consumers(self) -> List[str]:
        """列出所有消费者"""
        return list(self._consumers.keys())

    async def stop_all(self):
        """停止所有消费者"""
        for consumer in list(self._consumers.values()):
            await consumer.stop()
        self._consumers.clear()
        self.logger.info("All consumers stopped")

    def stop_all_cross_loop(self, timeout: float = 6.0) -> None:
        """在各自启动时的 event loop 上停止消费者（GUI 退出路径）。"""
        for queue_name, consumer in list(self._consumers.items()):
            loop = getattr(consumer, "_owner_loop", None)
            if loop is not None and loop.is_running():
                try:
                    asyncio.run_coroutine_threadsafe(
                        consumer.stop(), loop
                    ).result(timeout=timeout)
                except Exception as exc:
                    self.logger.warning(
                        "跨 loop 停止消费者 {} 失败: {}", queue_name, exc
                    )
            elif consumer.is_running():
                self.logger.warning(
                    "消费者 {} 仍在运行但 owner loop 不可用，跳过异步 stop",
                    queue_name,
                )
        self._consumers.clear()
        self.logger.info("All consumers stopped (cross-loop)")


message_consumer_manager = MessageConsumerManager()
