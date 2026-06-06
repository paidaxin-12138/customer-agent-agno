"""知识库兜底数据（产品卡片、FAQ 模板、同义词）— 从 JSON 加载，可配置覆盖。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from config import Config
from utils.logger_loguru import get_logger

from Agent.CustomerAgent.knowledge_fallback_data import (
    DEFAULT_FAQ_TEMPLATES,
    DEFAULT_PRODUCTS,
    DEFAULT_SYNONYMS,
)

_log = get_logger("KnowledgeFallback")


@lru_cache(maxsize=4)
def _load_json_file(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(path)
    raw = p.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"fallback JSON 根节点须为 object: {path}")
    return data


def load_knowledge_fallback(
    config: Config | None = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, List[str]]]:
    """
    返回 (products, faq_templates, synonyms)。
    配置键 ``knowledge_base.fallback_data_path`` 可指向自定义 JSON。
    """
    cfg = config or Config()
    custom = (cfg.get("knowledge_base.fallback_data_path", "") or "").strip()
    if not custom:
        return (
            list(DEFAULT_PRODUCTS),
            dict(DEFAULT_FAQ_TEMPLATES),
            dict(DEFAULT_SYNONYMS),
        )

    path = Path(custom)
    if not path.is_file():
        _log.warning("兜底 JSON 不存在，使用内置默认: {}", custom)
        return (
            list(DEFAULT_PRODUCTS),
            dict(DEFAULT_FAQ_TEMPLATES),
            dict(DEFAULT_SYNONYMS),
        )

    try:
        data = _load_json_file(str(path))
        products = data.get("products") or []
        faq = data.get("faq_templates") or {}
        synonyms = data.get("synonyms") or {}
        if not isinstance(products, list) or not isinstance(faq, dict):
            raise ValueError("products/faq_templates 结构无效")
        if not isinstance(synonyms, dict):
            synonyms = {}
        _log.info("已加载知识库兜底数据: {}", path)
        return products, faq, synonyms
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        _log.warning("加载兜底 JSON 失败 {}，使用内置默认: {}", custom, exc)
        return (
            list(DEFAULT_PRODUCTS),
            dict(DEFAULT_FAQ_TEMPLATES),
            dict(DEFAULT_SYNONYMS),
        )
