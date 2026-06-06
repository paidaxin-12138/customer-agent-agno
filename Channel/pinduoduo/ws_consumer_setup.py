"""店铺消息队列与消费者启动（从 pdd_chnnel 抽离）。"""
from __future__ import annotations

from typing import Any, Optional

from utils.logger_loguru import get_logger

_logger = get_logger("WSConsumerSetup")


async def setup_message_consumer(
    queue_name: str,
    *,
    business_hours: Optional[Any] = None,
    logger=None,
) -> None:
    """
    为店铺队列创建/重启 MessageConsumer 并挂载 handler 链。
    消费者已在运行则跳过（WS 重连场景）。
    """
    log = logger or _logger
    from Message import message_consumer_manager, queue_manager
    from Message.handler_chain_factory import handler_chain
    from Agent.CustomerAgent.agent import CustomerAgent

    existing_consumer = message_consumer_manager.get_consumer(queue_name)
    if existing_consumer and existing_consumer.is_running():
        log.debug(f"消费者 {queue_name} 已在运行，保持存活（重连不重启）")
        return
    if existing_consumer:
        log.info(f"消费者 {queue_name} 未运行，重新创建")
        try:
            await message_consumer_manager.stop_consumer(queue_name)
        except Exception as exc:
            log.warning(f"停止旧消费者失败: {queue_name}, {exc}")
        try:
            queue_manager.recreate_queue(queue_name)
        except Exception as exc:
            log.warning(f"重新创建队列失败: {queue_name}, {exc}")

    from config import get_config

    max_ai = int(get_config("chat.message_consumer_max_concurrent", 16) or 16)
    max_ai = max(1, min(max_ai, 50))
    consumer = message_consumer_manager.create_consumer(queue_name, max_concurrent=max_ai)

    try:
        from core.di_container import container

        bot = container.get(CustomerAgent)
    except Exception:
        bot = CustomerAgent()
    handlers = handler_chain(use_ai=True, bot=bot)
    for handler in handlers:
        consumer.add_handler(handler)

    await message_consumer_manager.start_consumer(queue_name)
    log.debug(f"消息消费者已启动: {queue_name}")
