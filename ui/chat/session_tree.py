# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""实时聊天 — 会话树展示辅助。"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QTreeWidgetItem

from utils.chat_time import format_chat_display_relative

_UNREAD_DOT_ICON: Optional[QIcon] = None


def unread_dot_icon(size: int = 10) -> QIcon:
    """未读红点（缓存单例）。"""
    global _UNREAD_DOT_ICON
    if _UNREAD_DOT_ICON is None:
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#FF3B30"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, size - 1, size - 1)
        painter.end()
        _UNREAD_DOT_ICON = QIcon(pm)
    return _UNREAD_DOT_ICON


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
    status = str(session.get("status") or "active").strip()
    closed_tag = "  ·  已结案" if status == "closed" else ""
    return f"{nick}  ·  {ts}{closed_tag}\n{prev or '（暂无消息）'}"


def apply_session_tree_item_visual(item: QTreeWidgetItem, session: Dict[str, Any]) -> None:
    """未读会话左侧显示红点；有未读时在工具提示中显示数量。"""
    unread = int(session.get("unread_count") or 0)
    if unread > 0:
        item.setIcon(0, unread_dot_icon())
        item.setToolTip(0, f"未读 {unread} 条")
    else:
        item.setIcon(0, QIcon())
        item.setToolTip(0, "")


def session_matches_filter(session: Dict[str, Any], query: str) -> bool:
    if not query:
        return True
    q = query.lower()
    nick = (session.get("buyer_nickname") or "").lower()
    prev = (session.get("last_message") or "").lower()
    buid = str(session.get("buyer_uid") or "").lower()
    return q in nick or q in prev or q in buid
