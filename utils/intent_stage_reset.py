# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
业务 stage 与用户新意图不一致时重置为 idle（避免长期锁死在改址/物流/售后流）。
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, Optional, Set

from config import get_config
from core.session_stages import BUSINESS_FLOW_STAGES

# 各业务 stage 仅允许「本流」意图；泛聊/询价应 reset 到 idle 交给 AI（勿含 general/greeting）
_STAGE_ALLOWED_INTENTS: Dict[str, FrozenSet[str]] = {
    "address_change": frozenset({"address_change"}),
    "await_confirm": frozenset({"address_change"}),
    "logistics": frozenset({"logistics"}),
    "after_sales": frozenset({"after_sales"}),
}

# 明显应切到商品问答的意图
_PRODUCT_INTENTS: FrozenSet[str] = frozenset(
    {"product_spec", "price", "general_product"}
)


def _intent_reset_enabled() -> bool:
    return bool(get_config("chat.intent_reset_enabled", True))


def _intent_reset_stages() -> Set[str]:
    raw = get_config(
        "chat.intent_reset_stages",
        ["address_change", "logistics", "after_sales", "await_confirm"],
    )
    if isinstance(raw, (list, tuple, set)):
        return {str(x).strip() for x in raw if str(x).strip()}
    return set(BUSINESS_FLOW_STAGES)


def _guess_intent(text: str) -> str:
    from Agent.CustomerAgent.conversation_memory import _guess_intent as guess

    return guess(text or "")


def should_reset_stage_for_intent(
    current_stage: str,
    guessed_intent: str,
    message_text: str = "",
    *,
    reset_stages: Optional[Set[str]] = None,
) -> bool:
    """当前 stage 为业务流且本轮意图明显不属于该流时返回 True。"""
    stage = (current_stage or "idle").strip()
    text = (message_text or "").strip()
    if stage == "idle":
        return False
    stages = reset_stages if reset_stages is not None else _intent_reset_stages()
    if stage not in stages:
        return False
    if stage in ("address_change", "await_confirm"):
        try:
            from utils.address_parse import is_address_change_intent

            if is_address_change_intent(text):
                return False
        except Exception:
            pass
    if stage == "logistics":
        from utils.logistics_intent import is_logistics_intent

        if is_logistics_intent(text):
            return False
    if stage == "after_sales":
        try:
            from utils.after_sales_policy import is_after_sales_related

            if is_after_sales_related(text):
                return False
        except Exception:
            pass
    intent = (guessed_intent or "general").strip()
    allowed = _STAGE_ALLOWED_INTENTS.get(stage, frozenset())
    if intent in allowed:
        return False
    if intent in _PRODUCT_INTENTS:
        return True
    if stage == "address_change" and intent in ("logistics", "after_sales", "price"):
        return True
    if stage == "logistics" and intent in ("address_change", "after_sales", "price", "product_spec"):
        return True
    if stage == "after_sales" and intent in ("address_change", "logistics", "price", "product_spec"):
        return True
    if intent not in allowed:
        return True
    return False


def try_intent_stage_reset(
    context: Any,
    metadata: Optional[Dict[str, Any]],
    *,
    message_text: Optional[str] = None,
) -> bool:
    """
    若需要重置则 update_session_state(stage=idle) 并刷新 context/metadata 缓存。
    返回是否已重置。
    """
    if not _intent_reset_enabled():
        return False
    from Agent.CustomerAgent.conversation_memory import (
        get_current_stage,
        resolve_session_id,
        transition_session_stage,
    )

    text = message_text
    if text is None:
        text = getattr(context, "content", None)
        if not isinstance(text, str):
            text = str(text or "")
    stage = get_current_stage(context, metadata)
    guessed = _guess_intent(text)
    if not should_reset_stage_for_intent(stage, guessed, text):
        return False
    sid = resolve_session_id(context, metadata)
    if sid is None:
        return False
    transition_session_stage(
        sid,
        stage="idle",
        intent=guessed,
        clear_flow_state=True,
        source_handler="IntentReset",
    )
    if metadata is not None:
        metadata["_session_stage"] = "idle"
    ku = getattr(context, "kwargs", None)
    if ku is not None:
        try:
            raw = dict(getattr(ku, "raw_data", None) or {})
            raw["_session_stage"] = "idle"
            if hasattr(ku, "raw_data"):
                ku.raw_data = raw
        except Exception:
            pass
    return True
