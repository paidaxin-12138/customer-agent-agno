# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
核心模块 - 提供系统基础设施功能
包括依赖注入、缓存、连接状态管理、工具类等
"""

from .di_container import DIContainer, container, configure_standard_services
from .cache import MemoryCache
from .base_service import BaseService
from .connection_status import ConnectionStatusManager, ConnectionState, ConnectionStatus

__all__ = [
    'DIContainer',
    'container',
    'configure_standard_services',
    'MemoryCache',
    'BaseService',
    'ConnectionStatusManager',
    'ConnectionState',
    'ConnectionStatus',
]