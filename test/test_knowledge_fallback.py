"""知识库兜底数据加载。"""

from __future__ import annotations

import json
from pathlib import Path

from Agent.CustomerAgent.knowledge_fallback import load_knowledge_fallback
from Agent.CustomerAgent.knowledge_fallback_data import (
    DEFAULT_FAQ_TEMPLATES,
    DEFAULT_PRODUCTS,
)


def test_builtin_fallback_has_products():
    products, faq, _synonyms = load_knowledge_fallback()
    assert len(products) == len(DEFAULT_PRODUCTS)
    assert "家用推荐" in faq
    assert faq["家用推荐"]["keywords"]


def test_custom_json_override(tmp_path, monkeypatch):
    custom = {
        "products": [{"id": "x", "name": "测试商品", "price": "$1"}],
        "faq_templates": {"测试": {"keywords": ["测"], "response": "好"}},
        "synonyms": {"测": ["试"]},
    }
    path = tmp_path / "fallback.json"
    path.write_text(json.dumps(custom, ensure_ascii=False), encoding="utf-8")

    class _Cfg:
        def get(self, key, default=None):
            if key == "knowledge_base.fallback_data_path":
                return str(path)
            return default

    products, faq, synonyms = load_knowledge_fallback(_Cfg())
    assert products[0]["id"] == "x"
    assert faq["测试"]["response"] == "好"
    assert synonyms["测"] == ["试"]
