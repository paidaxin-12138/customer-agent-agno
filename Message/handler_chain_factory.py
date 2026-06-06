"""
消息处理器链构建（独立模块，避免与 Message 包 __init__ 初始化顺序相关的 NameError）。
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional

from .core.handlers import CatchAllHandler

_cached_keyword_handler = None
_cached_address_change_handler = None
_cached_order_logistics_handler = None
_cached_image_video_handler = None
_cached_after_sales_apply_handler = None
_cached_buyer_emotion_handler = None

_HANDLER_LOAD_ERRORS: Dict[str, str] = {}
_CHAIN_AUDITED = False


class HandlerChainError(RuntimeError):
    """处理器链存在无法加载的 handler。"""


def get_handler_chain_status() -> Dict[str, Any]:
    """返回 handler 加载健康状态（供 /ready 与 /metrics）。"""
    return {
        "ok": len(_HANDLER_LOAD_ERRORS) == 0,
        "missing": sorted(_HANDLER_LOAD_ERRORS.keys()),
        "errors": dict(_HANDLER_LOAD_ERRORS),
        "audited": _CHAIN_AUDITED,
    }


def _reset_handler_caches() -> None:
    global _cached_keyword_handler, _cached_address_change_handler
    global _cached_order_logistics_handler, _cached_image_video_handler
    global _cached_after_sales_apply_handler, _cached_buyer_emotion_handler
    _cached_keyword_handler = None
    _cached_address_change_handler = None
    _cached_order_logistics_handler = None
    _cached_image_video_handler = None
    _cached_after_sales_apply_handler = None
    _cached_buyer_emotion_handler = None


def _record_handler_error(name: str, exc: Exception) -> None:
    from utils.logger_loguru import get_logger

    _HANDLER_LOAD_ERRORS[name] = str(exc)
    get_logger("handler_chain").error("Handler {} 加载失败: {}", name, exc)


def _load_handler(name: str, factory: Callable[[], Any]) -> Any:
    try:
        return factory()
    except ImportError as e:
        _record_handler_error(name, e)
        return None
    except Exception as e:
        _record_handler_error(name, e)
        return None


def audit_handler_chain(*, strict: bool = False) -> Dict[str, Any]:
    """
    预加载全部 handler 并记录缺失项。

    strict=True 或环境变量 STRICT_HANDLERS=1 时，存在缺失则抛出 HandlerChainError。
    """
    global _CHAIN_AUDITED
    global _cached_address_change_handler, _cached_order_logistics_handler
    global _cached_image_video_handler, _cached_after_sales_apply_handler
    global _cached_buyer_emotion_handler, _cached_keyword_handler

    _HANDLER_LOAD_ERRORS.clear()
    _reset_handler_caches()

    _cached_address_change_handler = _load_handler(
        "address_change",
        lambda: _import_handler("Message.handlers.address_change_handler", "AddressChangeHandler"),
    )
    _cached_order_logistics_handler = _load_handler(
        "order_logistics",
        lambda: _import_handler("Message.handlers.order_logistics_handler", "OrderLogisticsHandler"),
    )
    _cached_image_video_handler = _load_handler(
        "image_video",
        lambda: _import_handler("Message.handlers.image_video_handler", "ImageVideoHumanHandler"),
    )
    _cached_after_sales_apply_handler = _load_handler(
        "after_sales_apply",
        lambda: _import_handler("Message.handlers.after_sales_apply_handler", "AfterSalesApplyHandler"),
    )
    _cached_buyer_emotion_handler = _load_handler(
        "buyer_emotion",
        lambda: _import_handler("Message.handlers.buyer_emotion_handler", "BuyerEmotionHandler"),
    )
    _cached_keyword_handler = _load_handler(
        "keyword",
        lambda: _import_handler("Message.handlers.keyword_handler", "KeywordDetectionHandler"),
    )
    _load_handler("ai_reply", lambda: _create_ai_handler())

    _CHAIN_AUDITED = True
    status = get_handler_chain_status()
    strict = strict or os.getenv("STRICT_HANDLERS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if strict and not status["ok"]:
        raise HandlerChainError(
            "处理器链加载失败: " + ", ".join(status["missing"])
        )
    return status


def _import_handler(module_path: str, class_name: str) -> Any:
    import importlib

    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)()


def _get_image_video_handler():
    global _cached_image_video_handler
    if _cached_image_video_handler is None and "image_video" not in _HANDLER_LOAD_ERRORS:
        _cached_image_video_handler = _load_handler(
            "image_video",
            lambda: _import_handler("Message.handlers.image_video_handler", "ImageVideoHumanHandler"),
        )
    return _cached_image_video_handler


def _get_address_change_handler():
    global _cached_address_change_handler
    if _cached_address_change_handler is None and "address_change" not in _HANDLER_LOAD_ERRORS:
        _cached_address_change_handler = _load_handler(
            "address_change",
            lambda: _import_handler("Message.handlers.address_change_handler", "AddressChangeHandler"),
        )
    return _cached_address_change_handler


def _get_order_logistics_handler():
    global _cached_order_logistics_handler
    if _cached_order_logistics_handler is None and "order_logistics" not in _HANDLER_LOAD_ERRORS:
        _cached_order_logistics_handler = _load_handler(
            "order_logistics",
            lambda: _import_handler("Message.handlers.order_logistics_handler", "OrderLogisticsHandler"),
        )
    return _cached_order_logistics_handler


def _get_buyer_emotion_handler():
    global _cached_buyer_emotion_handler
    if _cached_buyer_emotion_handler is None and "buyer_emotion" not in _HANDLER_LOAD_ERRORS:
        _cached_buyer_emotion_handler = _load_handler(
            "buyer_emotion",
            lambda: _import_handler("Message.handlers.buyer_emotion_handler", "BuyerEmotionHandler"),
        )
    return _cached_buyer_emotion_handler


def _get_after_sales_apply_handler():
    global _cached_after_sales_apply_handler
    if _cached_after_sales_apply_handler is None and "after_sales_apply" not in _HANDLER_LOAD_ERRORS:
        _cached_after_sales_apply_handler = _load_handler(
            "after_sales_apply",
            lambda: _import_handler("Message.handlers.after_sales_apply_handler", "AfterSalesApplyHandler"),
        )
    return _cached_after_sales_apply_handler


def _get_keyword_handler():
    global _cached_keyword_handler
    if _cached_keyword_handler is None and "keyword" not in _HANDLER_LOAD_ERRORS:
        _cached_keyword_handler = _load_handler(
            "keyword",
            lambda: _import_handler("Message.handlers.keyword_handler", "KeywordDetectionHandler"),
        )
    return _cached_keyword_handler


def get_keyword_handler_instance():
    """供 UI 热加载关键词时获取已缓存的处理器实例。"""
    return _cached_keyword_handler


def _create_ai_handler(bot=None):
    from .handlers.ai_handler import AIReplyHandler

    return AIReplyHandler(bot)


def handler_chain(use_ai=True, bot=None):
    """简化版处理器链创建函数 - 包含关键词检测"""
    if not _CHAIN_AUDITED:
        audit_handler_chain()

    handlers: List[Any] = []

    ac_handler = _get_address_change_handler()
    if ac_handler is not None:
        handlers.append(ac_handler)

    ol_handler = _get_order_logistics_handler()
    if ol_handler is not None:
        handlers.append(ol_handler)

    as_handler = _get_after_sales_apply_handler()
    if as_handler is not None:
        handlers.append(as_handler)

    iv_handler = _get_image_video_handler()
    if iv_handler is not None:
        handlers.append(iv_handler)

    emotion_handler = _get_buyer_emotion_handler()
    if emotion_handler is not None:
        handlers.append(emotion_handler)

    keyword_handler = _get_keyword_handler()
    if keyword_handler is not None:
        handlers.append(keyword_handler)

    if use_ai and "ai_reply" not in _HANDLER_LOAD_ERRORS:
        try:
            handlers.append(_create_ai_handler(bot))
        except Exception as e:
            _record_handler_error("ai_reply", e)

    handlers.append(CatchAllHandler())

    return handlers
