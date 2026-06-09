# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
chat_sessions 单一读路径：解析 session_id、加载摘要、同步 ConversationHub 缓存。

SQLite（chat_sessions / chat_messages）为权威数据源；Hub 仅作 UI 索引与 Qt 信号，
写入后必须通过 ``sync_hub_session`` 从 DB 刷新摘要（含未读数）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, TYPE_CHECKING

from utils.logger_loguru import get_logger

if TYPE_CHECKING:
    from ui.conversation_hub import ConversationHub

_log = get_logger("SessionStore")


@dataclass(frozen=True)
class SessionSummary:
    session_id: int
    account_id: int
    buyer_uid: str
    buyer_nickname: str
    preview: str
    unread_count: int
    ai_mode: bool
    updated_at: float


def _session_id_from_row(row: Optional[Dict[str, Any]]) -> Optional[int]:
    if not row or row.get("id") is None:
        return None
    return int(row["id"])


def summary_from_row(row: Dict[str, Any]) -> SessionSummary:
    t = row.get("last_message_time") or row.get("updated_at")
    if t is not None:
        try:
            updated_at = float(t.timestamp())
        except AttributeError:
            updated_at = float(t) if t else 0.0
    else:
        updated_at = 0.0
    return SessionSummary(
        session_id=int(row["id"]),
        account_id=int(row.get("account_id") or 0),
        buyer_uid=str(row.get("buyer_uid") or ""),
        buyer_nickname=str(row.get("buyer_nickname") or "买家"),
        preview=str(row.get("last_message") or ""),
        unread_count=int(row.get("unread_count") or 0),
        ai_mode=bool(row.get("ai_mode", True)),
        updated_at=updated_at,
    )


def load_session_summary(session_id: int) -> Optional[SessionSummary]:
    from database.db_manager import db_manager

    row = db_manager.get_chat_session_by_id(int(session_id))
    if not row:
        return None
    return summary_from_row(row)


def resolve_session_by_buyer(
    account_id: int,
    buyer_uid: str,
    *,
    allow_any_status: bool = False,
) -> Optional[SessionSummary]:
    from database.db_manager import db_manager

    row = db_manager.get_chat_session_by_buyer(int(account_id), str(buyer_uid), "active")
    if not row and allow_any_status:
        row = db_manager.find_chat_session_by_buyer_any_status(
            int(account_id), str(buyer_uid)
        )
    if not row:
        return None
    return summary_from_row(row)


def resolve_session_id(
    *,
    channel_name: str,
    shop_id: str,
    seller_user_id: str,
    buyer_uid: str,
    allow_any_status: bool = False,
) -> Optional[int]:
    from database.db_manager import db_manager

    shop = str(shop_id or "").strip()
    seller = str(seller_user_id or "").strip()
    buyer = str(buyer_uid or "").strip()
    if not (shop and seller and buyer):
        return None
    acc = db_manager.get_account(str(channel_name or "pinduoduo"), shop, seller)
    if not acc or not acc.get("id"):
        return None
    row = db_manager.get_chat_session_by_buyer(int(acc["id"]), buyer, "active")
    if not row and allow_any_status:
        row = db_manager.find_chat_session_by_buyer_any_status(int(acc["id"]), buyer)
    return _session_id_from_row(row)


def resolve_session_id_from_context(
    context: Any,
    metadata: Optional[Dict[str, Any]] = None,
    *,
    allow_any_status: bool = False,
) -> Optional[int]:
    if context is None:
        return None
    meta = metadata or {}
    ch = str(
        meta.get("channel_name")
        or (context.channel_type.value if getattr(context, "channel_type", None) else "pinduoduo")
    )
    shop = str(meta.get("shop_id") or getattr(getattr(context, "kwargs", None), "shop_id", None) or "").strip()
    seller = str(meta.get("user_id") or getattr(getattr(context, "kwargs", None), "user_id", None) or "").strip()
    buyer = str(meta.get("from_uid") or getattr(getattr(context, "kwargs", None), "from_uid", None) or "").strip()
    if not buyer:
        ku = getattr(context, "kwargs", None)
        if ku and getattr(ku, "from_user", None) == "user":
            buyer = str(getattr(ku, "from_uid", "") or "").strip()
    if not (shop and seller and buyer):
        return None
    return resolve_session_id(
        channel_name=ch,
        shop_id=shop,
        seller_user_id=seller,
        buyer_uid=buyer,
        allow_any_status=allow_any_status,
    )


def get_ai_mode_for_context(context: Any, metadata: Dict[str, Any]) -> Optional[bool]:
    """读取 DB ai_mode；无法解析会话时返回 None。"""
    sid = resolve_session_id_from_context(context, metadata)
    if sid is None:
        return None
    summary = load_session_summary(sid)
    if summary is None:
        return None
    return summary.ai_mode


def load_session_stage(session_id: int) -> str:
    """从 task_state_json 读取当前 stage（供 metadata 预填）。"""
    import json

    from database.db_manager import db_manager

    mem = db_manager.get_session_memory(int(session_id)) or {}
    raw = mem.get("task_state_json")
    if not raw:
        return "idle"
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return "idle"
    stage = str(data.get("stage") or data.get("flow_node") or "idle").strip() or "idle"
    try:
        from Agent.CustomerAgent.conversation_memory import normalize_session_stage

        return normalize_session_stage(stage)
    except Exception:
        return stage


def set_ai_mode(session_id: int, ai_mode: bool) -> bool:
    """写入 ai_mode（SQLite 为权威）。"""
    from database.db_manager import db_manager

    return bool(db_manager.set_session_ai_mode(int(session_id), bool(ai_mode)))


def mark_session_read(session_id: int) -> bool:
    """标记会话消息已读并重置未读计数。"""
    from database.db_manager import db_manager

    return bool(db_manager.mark_chat_messages_read(int(session_id)))


def refresh_metadata_session(metadata: Dict[str, Any], session_id: int) -> None:
    """从 DB 刷新 metadata 中的 ai_mode / stage。"""
    metadata["session_id"] = int(session_id)
    summary = load_session_summary(int(session_id))
    if summary is not None:
        metadata["ai_mode"] = summary.ai_mode
    metadata["_session_stage"] = load_session_stage(int(session_id))


def sync_hub_for_buyer(
    hub: "ConversationHub",
    account_key: str,
    channel_name: str,
    shop_id: str,
    seller_user_id: str,
    buyer_uid: str,
) -> Optional[SessionSummary]:
    """persist 后按买家 UID 从 DB 刷新 Hub 摘要。"""
    from database.db_manager import db_manager

    acc = db_manager.get_account(channel_name, shop_id, seller_user_id)
    if not acc or not acc.get("id"):
        return None
    account_id = int(acc["id"])
    summary = resolve_session_by_buyer(account_id, str(buyer_uid))
    if summary is None:
        return None
    return sync_hub_session(hub, account_key, account_id, summary.session_id)


def sync_hub_session(
    hub: "ConversationHub",
    account_key: str,
    account_id: int,
    session_id: int,
) -> Optional[SessionSummary]:
    """用 DB 摘要刷新 Hub 内存（未读数以 chat_messages.is_read 为准）。"""
    summary = load_session_summary(session_id)
    if summary is None:
        return None
    hub.apply_db_summary(account_key, account_id, summary)
    return summary


def prime_metadata_session(
    metadata: Dict[str, Any],
    context: Any,
    *,
    allow_any_status: bool = False,
) -> None:
    """将 session_id / ai_mode 写入 metadata，供责任链只读 DB 一次。"""
    sid = resolve_session_id_from_context(
        context, metadata, allow_any_status=allow_any_status
    )
    if sid is None:
        return
    metadata["session_id"] = sid
    summary = load_session_summary(sid)
    if summary is not None:
        metadata["ai_mode"] = summary.ai_mode
    metadata["_session_stage"] = load_session_stage(sid)
