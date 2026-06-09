# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""从拼多多 MMS 拉取会话列表 / 最近消息（供软件与网页双端展示同步）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from config import get_config
from utils.logger_loguru import get_logger

_logger = get_logger("GetMessages")

# MMS latest_conversations 单条即「会话摘要 + 最后一条消息」
_MMS_TYPE_PREVIEW = {
    0: lambda c: str(c or "").strip(),
    1: lambda _: "[图片]",
    14: lambda _: "[视频]",
    19: lambda _: "[卡片]",
}


def _side_role(side: Any) -> str:
    if isinstance(side, dict):
        return str(side.get("role") or "").lower()
    return ""


def _side_uid(side: Any) -> Optional[str]:
    if isinstance(side, dict) and side.get("uid") is not None:
        return str(side.get("uid"))
    return None


def preview_from_mms_item(item: Dict[str, Any]) -> str:
    mtype = item.get("type")
    content = item.get("content")
    try:
        mtype_i = int(mtype)
    except (TypeError, ValueError):
        mtype_i = 0
    fn = _MMS_TYPE_PREVIEW.get(mtype_i, lambda c: str(c or "").strip() or "[消息]")
    text = fn(content)
    if not text:
        text = str(item.get("template_name") or "").strip() or "[消息]"
    return text[:500]


def parse_mms_conversation_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """解析 latest_conversations 单条为统一会话摘要。"""
    if not isinstance(item, dict):
        return None
    from_side = item.get("from") or {}
    to_side = item.get("to") or {}
    from_role = _side_role(from_side)
    to_role = _side_role(to_side)

    buyer_uid: Optional[str] = None
    sender_role = "agent"
    if from_role == "user":
        buyer_uid = _side_uid(from_side)
        sender_role = "customer"
    elif to_role == "user":
        buyer_uid = _side_uid(to_side)
        sender_role = "agent"
    else:
        return None

    if not buyer_uid:
        return None

    ts_raw = item.get("ts")
    try:
        ts = float(ts_raw) if ts_raw is not None else 0.0
    except (TypeError, ValueError):
        ts = 0.0

    msg_id = item.get("msg_id")
    if msg_id is not None:
        msg_id = str(msg_id)

    ctx = item.get("context") if isinstance(item.get("context"), dict) else {}
    unread = int(ctx.get("unread") or 0)

    nickname = ""
    for side in (from_side, to_side):
        if _side_role(side) == "user":
            nickname = str(side.get("nickname") or side.get("nick") or "").strip()
            if nickname:
                break

    return {
        "buyer_uid": buyer_uid,
        "buyer_nickname": nickname or "买家",
        "preview": preview_from_mms_item(item),
        "ts": ts,
        "msg_id": msg_id,
        "sender_role": sender_role,
        "msg_type": item.get("type"),
        "unread_hint": unread,
        "raw": item,
    }


class GetMessages:
    """MMS 会话列表（浏览器上下文 fetch，不占用 chat WebSocket）。"""

    def __init__(
        self,
        shop_id: str = "",
        user_id: str = "",
        channel_name: str = "pinduoduo",
        *,
        account_row: Optional[Dict[str, Any]] = None,
    ):
        self.shop_id = str(shop_id or "")
        self.user_id = str(user_id or "")
        self.channel_name = channel_name
        self._account_row = account_row

    def _resolve_account_row(self) -> Optional[Dict[str, Any]]:
        if self._account_row:
            row = self._account_row
        else:
            from database.db_manager import db_manager

            row = db_manager.get_account(self.channel_name, self.shop_id, self.user_id)
        if not row:
            return None
        if row.get("cookies"):
            return row
        from database.db_manager import db_manager

        return db_manager.get_account(self.channel_name, self.shop_id, self.user_id) or row

    def get_all_sessions(self, *, page_size: int = 50) -> List[Dict[str, Any]]:
        row = self._resolve_account_row()
        if not row or not row.get("cookies"):
            return []
        try:
            from Channel.pinduoduo.utils.mms_chat_browser import (
                get_or_create_chat_browser_session,
            )

            sess = get_or_create_chat_browser_session(row)
            data = sess.fetch_latest_conversations_raw_sync(size=page_size)
        except Exception as e:
            _logger.warning(
                "MMS 会话列表拉取失败 shop={} user={}: {}",
                self.shop_id,
                self.user_id,
                e,
            )
            return []

        result = data.get("result") if isinstance(data, dict) else {}
        items = []
        if isinstance(result, dict):
            items = result.get("conversations") or []
        if not isinstance(items, list):
            return []

        out: List[Dict[str, Any]] = []
        for item in items:
            parsed = parse_mms_conversation_item(item)
            if parsed:
                out.append(parsed)
        return out

    def get_chat_messages(
        self,
        buyer_uid: str,
        page: int = 1,
        page_size: int = 50,
    ) -> List[Dict[str, Any]]:
        """按买家 UID 过滤 latest_conversations（仅含各会话最后一条）。"""
        uid = str(buyer_uid or "").strip()
        if not uid:
            return []
        sessions = self.get_all_sessions(page_size=max(page_size, 50))
        return [s for s in sessions if str(s.get("buyer_uid")) == uid]
