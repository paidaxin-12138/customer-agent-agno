"""
生产后台服务：健康检查、定时备份、生命周期清理（独立 asyncio 线程，不阻塞 Qt）。
"""
from __future__ import annotations

import asyncio
import atexit
import threading
from typing import Optional

from core.schedule_utils import seconds_until_local
from utils.audit_log import audit_system_lifecycle
from utils.logger_loguru import get_logger

_logger = get_logger("ProductionServices")
_thread: Optional[threading.Thread] = None
_loop: Optional[asyncio.AbstractEventLoop] = None


def _cfg(key: str, default=None):
    try:
        from config import config

        return config.get(key, default)
    except Exception:
        return default


async def _backup_loop() -> None:
    if not bool(_cfg("production.backup_enabled", True)):
        return
    hour = int(_cfg("production.backup_hour", 2) or 2)
    minute = int(_cfg("production.backup_minute", 0) or 0)
    while True:
        wait = seconds_until_local(hour, minute)
        _logger.info("下次数据库备份约 {:.0f}s 后 ({}:{:02d})", wait, hour, minute)
        await asyncio.sleep(wait)
        try:
            from scripts.backup_db import backup_database

            dest = await asyncio.to_thread(backup_database)
            _logger.info("定时备份完成: {}", dest)
        except Exception as e:
            _logger.error("定时备份失败: {}", e)


async def _lifecycle_loop() -> None:
    hour = int(_cfg("retention.lifecycle_hour", 3) or 3)
    minute = int(_cfg("retention.lifecycle_minute", 0) or 0)
    while True:
        wait = seconds_until_local(hour, minute)
        _logger.info("下次生命周期清理约 {:.0f}s 后 ({}:{:02d})", wait, hour, minute)
        await asyncio.sleep(wait)
        try:
            from core.lifecycle_cleanup import run_lifecycle_cleanup

            await asyncio.to_thread(run_lifecycle_cleanup)
        except Exception as e:
            _logger.error("生命周期清理失败: {}", e)


async def _async_main() -> None:
    if bool(_cfg("production.health_enabled", True)):
        from core.health_server import start_health_server

        host = str(_cfg("production.health_host", "127.0.0.1"))
        port = int(_cfg("production.health_port", 8080) or 8080)
        await start_health_server(host, port)

    tasks = [
        asyncio.create_task(_backup_loop(), name="db_backup_loop"),
        asyncio.create_task(_lifecycle_loop(), name="lifecycle_loop"),
    ]
    await asyncio.gather(*tasks)


def _thread_target() -> None:
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    try:
        _loop.run_until_complete(_async_main())
    except Exception as e:
        _logger.error("生产后台服务异常退出: {}", e)
    finally:
        try:
            _loop.run_until_complete(_shutdown_async())
        except Exception:
            pass
        _loop.close()


async def _shutdown_async() -> None:
    from core.health_server import stop_health_server

    await stop_health_server()


def start_production_background_services() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    audit_system_lifecycle("system_startup", "应用启动，生产后台服务初始化")
    _thread = threading.Thread(target=_thread_target, name="ProductionServices", daemon=True)
    _thread.start()
    _logger.info("生产后台服务线程已启动")


def stop_production_background_services() -> None:
    audit_system_lifecycle("system_shutdown", "应用关闭")
    global _loop
    if _loop and _loop.is_running():
        asyncio.run_coroutine_threadsafe(_shutdown_async(), _loop)


atexit.register(lambda: audit_system_lifecycle("system_shutdown", "进程退出"))
