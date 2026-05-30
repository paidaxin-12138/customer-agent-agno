"""关键词处理器热加载（供 UI 在 DB 变更后调用）。"""
from __future__ import annotations

from utils.logger_loguru import get_logger

_logger = get_logger("KeywordReload")


def reload_keyword_handler() -> bool:
    try:
        from Message.handler_chain_factory import get_keyword_handler_instance

        handler = get_keyword_handler_instance()
        if handler is None:
            _logger.debug("关键词处理器未初始化，跳过热加载")
            return False
        handler.reload_keywords()
        return True
    except Exception as e:
        _logger.warning("关键词热加载失败: {}", e)
        return False
