# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""Message 包入口：队列、消费者、入队。"""
from __future__ import annotations

import asyncio

from bridge.context import Context
from config import get_config
from utils.logger_loguru import get_logger

from .core.consumer import MessageConsumer, message_consumer_manager
from .core.queue import QueueManager, SimpleMessageQueue, queue_manager

_log = get_logger("Message")


def _queue_put_retries() -> int:
    try:
        v = int(get_config("chat.queue_put_retries", 5) or 5)
        return max(1, min(v, 20))
    except (TypeError, ValueError):
        return 5


def _queue_put_retry_delay_sec() -> float:
    try:
        v = float(get_config("chat.queue_put_retry_delay_sec", 0.25) or 0.25)
        return max(0.05, min(v, 2.0))
    except (TypeError, ValueError):
        return 0.25


async def put_message(queue_name: str, context: Context) -> str:
    """向指定队列放入 Context 消息；队列满时按配置重试，仍失败则抛出 RuntimeError。"""
    try:
        from core.turn_abort import maybe_supersede_turn_on_enqueue

        maybe_supersede_turn_on_enqueue(context)
    except Exception as exc:
        _log.debug("maybe_supersede_turn_on_enqueue: {}", exc)
    queue = queue_manager.get_or_create_queue(queue_name)
    retries = _queue_put_retries()
    delay = _queue_put_retry_delay_sec()
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return await queue.put(context)
        except RuntimeError as e:
            if "Queue is full" not in str(e):
                raise
            last_err = e
            if attempt < retries:
                _log.warning(
                    "队列已满，{}s 后重试 ({}/{}) queue={}",
                    delay,
                    attempt,
                    retries,
                    queue_name,
                )
                await asyncio.sleep(delay)
            else:
                try:
                    from core.app_metrics import record_queue_enqueue_dropped

                    record_queue_enqueue_dropped(queue_name)
                except Exception:
                    pass
                letter_id = None
                try:
                    from Message.dead_letter import persist_dead_letter

                    letter_id = persist_dead_letter(
                        queue_name, context, reason="queue_full_exhausted"
                    )
                except Exception as dl_err:
                    _log.debug("dead-letter 写入失败: {}", dl_err)
                if letter_id is not None:
                    _log.error(
                        "队列已满，重试 {} 次后写入 dead-letter id={} queue={}",
                        retries,
                        letter_id,
                        queue_name,
                    )
                    return f"dead-letter:{letter_id}"
                _log.error(
                    "队列已满，重试 {} 次后仍无法入队 queue={}",
                    retries,
                    queue_name,
                )
    if last_err:
        raise last_err
    raise RuntimeError("Queue is full")


__all__ = [
    "Context",
    "MessageConsumer",
    "QueueManager",
    "SimpleMessageQueue",
    "message_consumer_manager",
    "put_message",
    "queue_manager",
]
