"""
按需 RAG 判定（V4 Phase 1）：四维度联合决定是否触发知识库检索。
"""

from __future__ import annotations

PRODUCT_INTENTS = frozenset({"product_spec", "price", "general_product"})
PRODUCT_STAGES = frozenset({"product_qa", "recommend"})
FLOW_NO_RAG_STAGES = frozenset({"address_change", "after_sales", "logistics"})
NO_RAG_INTENTS = frozenset({"chat", "greeting"})

_FOLLOW_UP_MARKERS = (
    "运费",
    "包邮",
    "多少钱",
    "价格",
    "贵不贵",
    "有货",
    "规格",
    "颜色",
)


def _is_follow_up_product_question(last_intent: str | None, text: str) -> bool:
    if last_intent not in PRODUCT_INTENTS:
        return False
    t = text or ""
    return any(m in t for m in _FOLLOW_UP_MARKERS)


def need_retrieval(
    *,
    intent: str,
    stage: str,
    handler_already_processed: bool,
    last_intent: str | None,
    current_text: str,
) -> bool:
    if handler_already_processed:
        return False

    intent = (intent or "general").strip()
    stage = (stage or "idle").strip()

    if intent in NO_RAG_INTENTS:
        return False
    if stage in FLOW_NO_RAG_STAGES:
        return False
    if intent in PRODUCT_INTENTS or stage in PRODUCT_STAGES:
        return True
    if _is_follow_up_product_question(last_intent, current_text):
        return True
    return False
