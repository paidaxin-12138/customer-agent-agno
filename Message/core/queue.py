# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
简化的消息队列实现
只支持FIFO队列，移除未使用的复杂功能
"""

import asyncio
import hashlib
import time
from collections import OrderedDict
from typing import Optional, Dict, Set
from utils.logger_loguru import get_logger
from config import get_config

from ..models.queue_models import MessageWrapper, QueueStats, QueueConfig
from bridge.context import Context


logger = get_logger(__name__)


class SimpleMessageQueue:
    """简化的消息队列 - 只支持FIFO"""

    def __init__(self, name: str, config: QueueConfig):
        self.name = name
        self.config = config
        self.logger = get_logger(f"Queue.{name}")

        # 基本队列
        self._queue = asyncio.Queue(maxsize=config.max_size)
        self._stats = QueueStats()
        self._closed = False

        # 去重缓存（可选）
        self._deduplication_cache: Optional[OrderedDict[str, float]] = (
            OrderedDict() if config.enable_deduplication else None
        )
        self._last_cleanup_time = time.time()

    async def put(self, context: Context) -> str:
        """放入消息"""
        if self._closed:
            raise RuntimeError("Queue is closed")

        message_wrapper = MessageWrapper(
            message_id="",  # 将在__post_init__中生成
            context=context,
            timestamp=time.time()
        )

        # 检查去重（返回空串表示未入队，与正常 message_id 区分）
        if self._should_deduplicate(message_wrapper):
            from_uid = ""
            try:
                from_uid = str(
                    getattr(
                        getattr(message_wrapper.context, "kwargs", None), "from_uid", ""
                    )
                    or ""
                )
            except Exception:
                pass
            self.logger.info(
                "[DEDUP] queue={} skipped from_uid={}",
                self.name,
                from_uid,
            )
            return ""

        force_enqueue = bool(get_config("chat.queue_force_enqueue", False))
        if self._queue.full():
            if force_enqueue:
                dropped = 0
                while self._queue.full():
                    try:
                        self._queue.get_nowait()
                        dropped += 1
                        self._stats.dequeue()
                    except asyncio.QueueEmpty:
                        break
                if dropped:
                    self.logger.warning(
                        "Queue {} full: dropped {} oldest message(s) to force enqueue",
                        self.name,
                        dropped,
                    )
            else:
                self._stats.total_enqueued += 1  # 计入统计但拒绝
                raise RuntimeError("Queue is full")

        try:
            await self._queue.put(message_wrapper)
            self._stats.enqueue()
            ctx = message_wrapper.context
            from_uid = ""
            try:
                from_uid = str(getattr(getattr(ctx, "kwargs", None), "from_uid", "") or "")
            except Exception:
                pass
            self.logger.info(
                "[ENQUEUE] queue={} wrapper_id={} type={} from_uid={}",
                self.name,
                message_wrapper.message_id,
                getattr(ctx, "type", "?"),
                from_uid,
            )
            return message_wrapper.message_id

        except asyncio.QueueFull:
            if force_enqueue:
                while self._queue.full():
                    try:
                        self._queue.get_nowait()
                        self._stats.dequeue()
                    except asyncio.QueueEmpty:
                        break
                await self._queue.put(message_wrapper)
                self._stats.enqueue()
                return message_wrapper.message_id
            raise RuntimeError("Queue is full")

    async def get(self, timeout: Optional[float] = None) -> Optional[MessageWrapper]:
        """获取消息"""
        if self._closed and self._queue.empty():
            return None

        try:
            if timeout:
                wrapper = await asyncio.wait_for(self._queue.get(), timeout)
            else:
                wrapper = await self._queue.get()

            self._stats.dequeue()
            self.logger.debug(f"Message dequeued: {wrapper.message_id}")
            return wrapper

        except asyncio.TimeoutError:
            return None

    def size(self) -> int:
        """获取队列大小"""
        return self._queue.qsize()

    def is_empty(self) -> bool:
        """检查队列是否为空"""
        return self._queue.empty()

    def get_stats(self) -> QueueStats:
        """获取统计信息"""
        stats = QueueStats(
            total_enqueued=self._stats.total_enqueued,
            total_dequeued=self._stats.total_dequeued,
            current_size=self.size(),
            last_activity=self._stats.last_activity
        )
        return stats

    def close(self):
        """关闭队列"""
        self._closed = True
        self.logger.info(f"Queue {self.name} closed")

    def _should_deduplicate(self, wrapper: MessageWrapper) -> bool:
        """检查是否应该去重"""
        if self._deduplication_cache is None:
            return False

        raw = wrapper.context.content
        if isinstance(raw, (dict, list)):
            import json

            norm = json.dumps(raw, sort_keys=True, ensure_ascii=False)
        else:
            norm = str(raw or "")
        buyer_key = ""
        try:
            ku = getattr(wrapper.context, "kwargs", None)
            buyer_key = str(getattr(ku, "from_uid", "") or "")
        except Exception:
            pass
        dedup_key = f"{buyer_key}|{norm}"
        content_hash = hashlib.sha256(dedup_key.encode("utf-8")).hexdigest()[:32]
        if content_hash in self._deduplication_cache:
            return True

        self._deduplication_cache[content_hash] = time.time()
        self._cleanup_deduplication_cache()
        return False

    def _cleanup_deduplication_cache(self) -> None:
        """LRU + TTL 清理去重缓存，避免无限增长。"""
        current_time = time.time()
        window = float(self.config.deduplication_window or 300)
        max_keys = 5000
        expired = [
            k
            for k, ts in self._deduplication_cache.items()
            if current_time - ts > window
        ]
        for k in expired:
            self._deduplication_cache.pop(k, None)
        while len(self._deduplication_cache) > max_keys:
            self._deduplication_cache.popitem(last=False)
        self._last_cleanup_time = current_time

    async def clear(self):
        """清空队列"""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.logger.info(f"Queue {self.name} cleared")


class QueueManager:
    """队列管理器 - 简化版"""

    def __init__(self):
        self._queues: Dict[str, SimpleMessageQueue] = {}
        self.logger = get_logger("QueueManager")

    def get_or_create_queue(self, name: str, config: Optional[QueueConfig] = None) -> SimpleMessageQueue:
        """获取或创建队列"""
        if name not in self._queues:
            if config is None:
                config = QueueConfig()
            queue = SimpleMessageQueue(name, config)
            self._queues[name] = queue
            self.logger.debug(f"Created queue: {name}")
        return self._queues[name]

    def get_queue(self, name: str) -> Optional[SimpleMessageQueue]:
        """获取队列"""
        return self._queues.get(name)

    def recreate_queue(self, name: str, config: Optional[QueueConfig] = None) -> SimpleMessageQueue:
        """重新创建队列以绑定当前事件循环"""
        try:
            old = self._queues.get(name)
            if old:
                old.close()
                self._queues.pop(name, None)
        except Exception as e:
            self.logger.debug(f"recreate_queue 关闭旧队列: {e}")
        if config is None:
            config = QueueConfig()
        queue = SimpleMessageQueue(name, config)
        self._queues[name] = queue
        self.logger.info(f"Recreated queue: {name}")
        return queue

    def list_queues(self) -> Dict[str, QueueStats]:
        """列出所有队列及其统计信息"""
        return {name: queue.get_stats() for name, queue in self._queues.items()}

    async def close_all(self):
        """关闭所有队列"""
        for queue in self._queues.values():
            queue.close()
        self.logger.info("All queues closed")


# 全局队列管理器实例
queue_manager = QueueManager()
