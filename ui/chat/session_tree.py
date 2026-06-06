"""实时聊天 — 会话树展示辅助。"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from utils.chat_time import format_chat_display_relative


def session_sort_key(session: Dict[str, Any]) -> Tuple[bool, int, float]:
    """未读优先，其次最近消息时间。"""
    unread = int(session.get("unread_count") or 0)
    t = session.get("last_message_time") or session.get("updated_at")
    ts = t.timestamp() if hasattr(t, "timestamp") else 0.0
    return (unread > 0, unread, ts)


def format_account_tree_label(
    acc: Dict[str, Any], status_text: str, unread: int
) -> str:
    shop = (acc.get("shop_name") or "店铺").strip()
    user = (acc.get("username") or "").strip()
    if len(shop) > 16:
        shop = shop[:15] + "…"
    status = f"未读 {unread}" if unread else status_text
    return f"{shop}\n{user}  ·  {status}"


def format_session_tree_label(session: Dict[str, Any]) -> str:
    t = session.get("last_message_time") or session.get("updated_at")
    ts = format_chat_display_relative(t) if t else ""
    prev = (session.get("last_message") or "").strip()
    if len(prev) > 42:
        prev = prev[:41] + "…"
    nick = (session.get("buyer_nickname") or "买家").strip()
    if len(nick) > 12:
        nick = nick[:11] + "…"
    unread = int(session.get("unread_count") or 0)
    unread_suffix = f"  ·  未读{unread}" if unread else ""
    return f"{nick}  ·  {ts}{unread_suffix}\n{prev or '（暂无消息）'}"


def session_matches_filter(session: Dict[str, Any], query: str) -> bool:
    if not query:
        return True
    q = query.lower()
    nick = (session.get("buyer_nickname") or "").lower()
    prev = (session.get("last_message") or "").lower()
    buid = str(session.get("buyer_uid") or "").lower()
    return q in nick or q in prev or q in buid
