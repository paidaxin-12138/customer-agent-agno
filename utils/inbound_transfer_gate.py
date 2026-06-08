"""
接待专用子账号：仅在收到平台 TRANSFER 后才允许责任链截流（AI/规则处理）。

未转接入线的买家消息仍写入会话列表，但不触发 AI 回复或转接逻辑。
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Set

from bridge.context import Context, ContextType
from config import get_config
from utils.logger_loguru import get_logger

_log = get_logger("InboundTransferGate")


def gate_until_transfer_enabled() -> bool:
    return bool(get_config("chat.inbound_transfer_gate_until_received", True))


def preferred_reception_seller_ids() -> Set[str]:
    raw = get_config("chat.preferred_transfer_seller_user_ids") or []
    if not isinstance(raw, list):
        raw = [raw]
    out: Set[str] = set()
    for item in raw:
        s = str(item or "").strip()
        if not s:
            continue
        if s.startswith("cs_"):
            parts = s.split("_")
            if len(parts) >= 3:
                out.add(parts[-1])
                continue
        out.add(s)
    return out


def is_preferred_reception_seller(shop_id: Any, seller_user_id: Any) -> bool:
    preferred = preferred_reception_seller_ids()
    if not preferred:
        return False
    uid = str(seller_user_id or "").strip()
    return uid in preferred


def is_preferred_reception_account_id(account_id: int) -> bool:
    try:
        from database.db_manager import db_manager

        row = db_manager.get_account_row_by_id(int(account_id))
        if not row:
            return False
        return is_preferred_reception_seller(
            row.get("platform_shop_id"),
            row.get("seller_user_id"),
        )
    except Exception:
        return False


def default_ai_mode_for_new_session(account_id: int) -> bool:
    """接待专用号新建会话默认人工，待 TRANSFER 后再由截流切 AI。"""
    if gate_until_transfer_enabled() and is_preferred_reception_account_id(account_id):
        return False
    return True


def mark_inbound_transferred(session_id: int) -> None:
    from database.db_manager import db_manager

    db_manager.mark_chat_session_inbound_transferred(int(session_id))


def is_inbound_transferred(session_id: int) -> bool:
    from database.db_manager import db_manager

    return db_manager.is_chat_session_inbound_transferred(int(session_id))


def resolve_session_id(context: Context, metadata: Dict[str, Any]) -> Optional[int]:
    from database.session_store import resolve_session_id_from_context

    return resolve_session_id_from_context(
        context, metadata, allow_any_status=True
    )


def should_block_handler_until_transfer(
    context: Context,
    metadata: Dict[str, Any],
) -> bool:
    """True = 跳过责任链（未收到转接的接待号会话）。"""
    try:
        from utils.weak_supervision import effective_inbound_transfer_gate

        if not effective_inbound_transfer_gate():
            return False
    except Exception:
        if not gate_until_transfer_enabled():
            return False
    if context.type == ContextType.TRANSFER:
        return False
    try:
        ku = getattr(context, "kwargs", None)
        raw = getattr(ku, "raw_data", None) if ku else None
        if isinstance(raw, dict) and raw.get("_transfer_takeover"):
            return False
    except Exception:
        pass

    shop_id = metadata.get("shop_id")
    user_id = metadata.get("user_id")
    if not is_preferred_reception_seller(shop_id, user_id):
        return False

    sid = resolve_session_id(context, metadata)
    if sid is None:
        return True
    return not is_inbound_transferred(sid)
