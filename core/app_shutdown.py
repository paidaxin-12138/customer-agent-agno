"""应用退出时统一释放 WebSocket、消费者、后台服务等资源。"""
from __future__ import annotations

import asyncio
import threading

from utils.logger_loguru import get_logger

_logger = get_logger("AppShutdown")
_lock = threading.Lock()
_done = False

SHUTDOWN_TIMEOUT_SEC = 5.0


async def stop_all_services() -> None:
    """异步停止自动回复、WebSocket、消息消费者、Watchdog 与生产后台服务。"""
    _logger.info("正在停止所有后台服务…")

    try:
        from ui.auto_reply_ui import auto_reply_manager

        await asyncio.to_thread(auto_reply_manager.stop_all)
    except Exception as e:
        _logger.warning("停止自动回复失败: {}", e)

    try:
        from core.pdd_channel_registry import iter_registered_channels

        channels = iter_registered_channels()
        for channel in channels:
            close_ws = getattr(channel, "close_websocket", None)
            if callable(close_ws):
                await close_ws()
    except Exception as e:
        _logger.debug("关闭 WebSocket 连接: {}", e)

    try:
        from Message.core.consumer import message_consumer_manager

        await message_consumer_manager.stop_all()
    except Exception as e:
        _logger.debug("停止消息消费者: {}", e)

    try:
        from Message.handlers.ai_reply_watchdog import cancel_all_watchdogs

        await cancel_all_watchdogs()
    except Exception as e:
        _logger.debug("取消 Watchdog 任务: {}", e)

    try:
        from core.production_services import stop_production_background_services

        stop_production_background_services()
    except Exception as e:
        _logger.debug("停止生产后台服务: {}", e)

    _logger.info("所有后台服务已停止")


def run_stop_all_services_sync(timeout: float = SHUTDOWN_TIMEOUT_SEC) -> None:
    """在 GUI 主线程同步执行异步清理，带超时保护。"""
    try:
        asyncio.run(asyncio.wait_for(stop_all_services(), timeout=timeout))
    except asyncio.TimeoutError:
        _logger.warning("停止后台服务超时（{}s），强制退出", timeout)
    except Exception as e:
        _logger.warning("停止后台服务异常: {}", e)


def shutdown_application() -> None:
    """可重复调用；在 QApplication.aboutToQuit 与主窗口关闭时执行。"""
    global _done
    with _lock:
        if _done:
            return
        _done = True

    _logger.info("应用正在退出，开始清理后台资源…")
    try:
        from database.chat_message_buffer import flush_chat_message_buffer

        flushed = flush_chat_message_buffer()
        if flushed:
            _logger.info("退出前刷新 chat_messages 缓冲 {} 条", flushed)
    except Exception as exc:
        _logger.debug("chat_messages 缓冲刷新跳过: {}", exc)
    run_stop_all_services_sync(SHUTDOWN_TIMEOUT_SEC)
    _logger.info("应用退出清理完成")
