# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
基于loguru的日志模块 - 提供全局日志功能，支持结构化日志和异步处理
"""

import os
import sys
import json
import uuid
import weakref
from datetime import datetime
from typing import Any, Dict, Optional, Union
from pathlib import Path

from loguru import logger

# 生产日志（TimedRotating + PM2 out/error）在首次 get_logger 时初始化
_LOG_SETUP_DONE = False


def _ensure_log_setup() -> None:
    global _LOG_SETUP_DONE
    if _LOG_SETUP_DONE:
        return
    try:
        from utils.logging_setup import setup_production_logging

        setup_production_logging()
    except Exception:
        pass
    _LOG_SETUP_DONE = True


# 可选的PyQt6依赖
try:
    from PyQt6.QtCore import QObject, pyqtSignal
    PYQT6_AVAILABLE = True
except ImportError:
    PYQT6_AVAILABLE = False
    # 创建占位符类
    class QObject:
        def __init__(self, *args, **kwargs):
            pass
    def pyqtSignal(*args):
        class DummySignal:
            def emit(self, *args, **kwargs):
                pass
            def connect(self, *args, **kwargs):
                pass
            def disconnect(self, *args, **kwargs):
                pass
        return DummySignal()

DEFAULT_LOG_LEVEL = "info"

# 全局logger对象（保持向后兼容）
app_logger = logger

def get_logger(name=None):
    """
    获取logger实例

    Args:
        name: logger名称，如果为None则使用调用模块的名称

    Returns:
        loguru logger实例
    """
    _ensure_log_setup()
    if name is None:
        # 获取调用者的模块名
        import inspect
        frame = inspect.currentframe().f_back
        name = frame.f_globals.get('__name__', 'unknown')

        # 如果是__main__, 使用文件名
        if name == '__main__':
            filename = frame.f_globals.get('__file__', 'main')
            name = os.path.splitext(os.path.basename(filename))[0]

    # 绑定模块名称到logger
    return logger.bind(module=name)

# 导出全局日志对象和获取logger的函数
__all__ = ["logger", "app_logger", "get_logger", "BusinessLogger", "get_business_logger", "log_with_ctx"]

class BusinessLogger:
    """业务日志记录器，基于loguru实现"""

    def __init__(self, module_name: str):
        self.module_name = module_name
        self.logger = logger.bind(business=True, module=module_name)

    def log_message_process(self, user_id: str, message_type: str, processing_time: float, **kwargs) -> None:
        """记录消息处理事件"""
        self.logger.info(
            "消息处理完成",
            extra={
                "event_type": "message_processed",
                "user_id": user_id,
                "message_type": message_type,
                "processing_time_ms": round(processing_time * 1000, 2),
                **kwargs
            }
        )

    def log_agent_response(self, user_id: str, query_length: int, response_length: int, response_time: float, **kwargs) -> None:
        """记录Agent响应事件"""
        self.logger.info(
            "Agent响应生成",
            extra={
                "event_type": "agent_response",
                "user_id": user_id,
                "query_length": query_length,
                "response_length": response_length,
                "response_time_ms": round(response_time * 1000, 2),
                **kwargs
            }
        )

    def log_error(self, error_type: str, error_message: str, user_id: Optional[str] = None, **kwargs) -> None:
        """记录业务错误"""
        self.logger.error(
            "业务错误",
            extra={
                "event_type": "business_error",
                "error_type": error_type,
                "error_message": error_message,
                "user_id": user_id,
                **kwargs
            }
        )

    def log_performance(self, operation: str, duration: float, **kwargs) -> None:
        """记录性能指标"""
        self.logger.info(
            "性能指标",
            extra={
                "event_type": "performance_metric",
                "operation": operation,
                "duration_ms": round(duration * 1000, 2),
                **kwargs
            }
        )

def get_business_logger(module_name: str) -> BusinessLogger:
    """获取业务日志记录器实例"""
    return BusinessLogger(module_name)


def _ui_log_redact_filter(record) -> bool:
    """UI 日志 sink 脱敏（与 production loguru filter 一致）。"""
    try:
        from utils.logging_setup import _loguru_redact_filter

        return _loguru_redact_filter(record)
    except Exception:
        return True


# UI集成部分
class UILogHandler(QObject):
    """UI日志处理器：延迟注册 loguru sink，销毁时自动卸载。"""

    log_received = pyqtSignal(str, str, object)  # level, message, record

    def __init__(self, parent=None):
        super().__init__(parent)
        self.handler_id: Optional[int] = None
        self.destroyed.connect(self._on_destroyed)

    def _on_destroyed(self, *_args) -> None:
        self.uninstall()

    def emit(self, record):
        """为了兼容性保留"""
        pass

    def install(self) -> None:
        """注册 loguru → Qt 信号桥（可重复调用，幂等）。"""
        if self.handler_id is not None:
            return
        weak_self = weakref.ref(self)

        def ui_sink(message):
            inst = weak_self()
            if inst is None:
                return
            try:
                record = message.record
                inst.log_received.emit(
                    record["level"].name,
                    record["message"],
                    record,
                )
            except RuntimeError:
                inst.uninstall()

        self.handler_id = logger.add(
            ui_sink,
            level="DEBUG",
            catch=True,
            filter=_ui_log_redact_filter,
        )

    def uninstall(self) -> None:
        """从 loguru 移除 sink，避免 Qt 对象销毁后仍被回调。"""
        if self.handler_id is not None:
            try:
                logger.remove(self.handler_id)
            except ValueError:
                pass
            self.handler_id = None

# 上下文日志功能
def format_conn_key(shop_id: Optional[str], user_id: Optional[str]) -> str:
    """格式化连接键"""
    if not shop_id or not user_id:
        return "unknown_unknown"
    return f"{shop_id}_{user_id}"

def log_with_ctx(logger_name: str, msg: str, shop_id: Optional[str] = None,
                 user_id: Optional[str] = None, username: Optional[str] = None,
                 from_uid: Optional[str] = None):
    """带上下文的日志记录"""
    context_parts = []
    if shop_id or user_id:
        context_parts.append(f"key={format_conn_key(shop_id, user_id)}")
    if username:
        context_parts.append(f"user={username}")
    if from_uid:
        context_parts.append(f"from_uid={from_uid}")

    context = f"{' '.join(context_parts)} | " if context_parts else ""
    logger.bind(context=context, logger_name=logger_name).info(f"{context}{msg}")