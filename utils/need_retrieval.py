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
    "哪款",
    "有没有",
    "白色",
    "黑色",
)

# 含以下词时不再视为商品追问（避免「价格不合适要退款」误开 RAG）
_FOLLOW_UP_BLOCKERS = (
    "退款",
    "退货",
    "换货",
    "售后",
    "投诉",
    "物流",
    "快递",
    "发货",
    "改址",
    "改地址",
    "收货地址",
    "转人工",
    "人工客服",
)


def resolve_retrieval_intent(
    *,
    guessed_intent: str,
    task_intent: str | None,
) -> str:
    """合并本轮猜测与持久化 intent，避免 idle 下 task 仍为 product 时漏 RAG。"""
    guessed = (guessed_intent or "general").strip() or "general"
    persisted = (task_intent or "").strip()
    if guessed in PRODUCT_INTENTS:
        return guessed
    if persisted in PRODUCT_INTENTS and guessed in ("general", "chat", ""):
        return persisted
    if persisted and persisted not in NO_RAG_INTENTS and guessed == "general":
        return persisted
    return guessed


def _is_follow_up_product_question(last_intent: str | None, text: str) -> bool:
    if last_intent not in PRODUCT_INTENTS:
        return False
    t = text or ""
    if any(b in t for b in _FOLLOW_UP_BLOCKERS):
        return False
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
