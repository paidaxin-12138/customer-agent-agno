"""
消息处理器链构建（独立模块，避免与 Message 包 __init__ 初始化顺序相关的 NameError）。
"""

from __future__ import annotations

from .core.handlers import CatchAllHandler

_cached_keyword_handler = None
_cached_order_logistics_handler = None
_cached_image_video_handler = None


def _get_image_video_handler():
    global _cached_image_video_handler
    if _cached_image_video_handler is None:
        try:
            from .handlers.image_video_handler import ImageVideoHumanHandler

            _cached_image_video_handler = ImageVideoHumanHandler()
        except ImportError as e:
            from utils.logger_loguru import get_logger

            get_logger("handler_chain").warning(f"ImageVideoHumanHandler 导入失败: {e}")
    return _cached_image_video_handler


def _get_order_logistics_handler():
    """订单修改 / 物流查询处理器（拼多多开放平台物流轨迹）。"""
    global _cached_order_logistics_handler
    if _cached_order_logistics_handler is None:
        try:
            from .handlers.order_logistics_handler import OrderLogisticsHandler

            _cached_order_logistics_handler = OrderLogisticsHandler()
        except ImportError as e:
            from utils.logger_loguru import get_logger

            get_logger("handler_chain").warning(f"OrderLogisticsHandler 导入失败: {e}")
    return _cached_order_logistics_handler


def _get_keyword_handler():
    """获取或创建缓存的关键词检测处理器"""
    global _cached_keyword_handler
    if _cached_keyword_handler is None:
        try:
            from .handlers.keyword_handler import KeywordDetectionHandler

            _cached_keyword_handler = KeywordDetectionHandler()
        except ImportError as e:
            from utils.logger_loguru import get_logger

            get_logger("handler_chain").warning(f"关键词检测处理器导入失败: {e}")
    return _cached_keyword_handler


def _create_ai_handler(bot=None):
    from .handlers.ai_handler import AIReplyHandler

    return AIReplyHandler(bot)


def handler_chain(use_ai=True, businessHours=None, bot=None):
    """简化版处理器链创建函数 - 包含关键词检测"""
    handlers = []

    ol_handler = _get_order_logistics_handler()
    if ol_handler is not None:
        handlers.append(ol_handler)

    iv_handler = _get_image_video_handler()
    if iv_handler is not None:
        handlers.append(iv_handler)

    keyword_handler = _get_keyword_handler()
    if keyword_handler is not None:
        handlers.append(keyword_handler)

    if use_ai:
        handlers.append(_create_ai_handler(bot))

    handlers.append(CatchAllHandler())

    return handlers
