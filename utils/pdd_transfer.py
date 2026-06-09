# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""拼多多会话转接：从 Context / raw_data 解析买家 UID，及转接目标客服选择。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from bridge.context import Context, ContextType

_CS_UID_RE = re.compile(r"^cs_", re.I)
_DIGIT_UID_RE = re.compile(r"^\d{6,}$")


def _role_is_user(role: Any) -> bool:
    return str(role or "").lower() == "user"


def _pick_uid_from_block(block: Any) -> Optional[str]:
    if not isinstance(block, dict):
        return None
    uid = block.get("uid")
    if uid is None:
        return None
    s = str(uid).strip()
    if not s or _CS_UID_RE.match(s):
        return None
    if _DIGIT_UID_RE.match(s):
        return s
    return None


def _pick_from_mapping(data: Any, keys: tuple[str, ...]) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    for key in keys:
        v = data.get(key)
        if v is None:
            continue
        s = str(v).strip()
        if s and not _CS_UID_RE.match(s) and _DIGIT_UID_RE.match(s):
            return s
    return None


def resolve_buyer_uid_from_transfer(context: Context) -> Optional[str]:
    """
    从转接推送（type=24）解析买家 UID。
    优先 message.from/to 中 role=user 的一侧，其次 info/data 字段。
    """
    if context.type != ContextType.TRANSFER:
        return None

    ku = context.kwargs
    if _role_is_user(getattr(ku, "to_user", None)) and getattr(ku, "to_uid", None):
        s = str(ku.to_uid).strip()
        if s and not _CS_UID_RE.match(s):
            return s
    if _role_is_user(getattr(ku, "from_user", None)) and getattr(ku, "from_uid", None):
        s = str(ku.from_uid).strip()
        if s and not _CS_UID_RE.match(s):
            return s

    raw = getattr(ku, "raw_data", None) or {}
    if isinstance(raw, dict):
        msg = raw.get("message") or {}
        if isinstance(msg, dict):
            for side in ("to", "from"):
                uid = _pick_uid_from_block(msg.get(side))
                if uid:
                    return uid
            for nested in (msg.get("info"), msg.get("data")):
                uid = _pick_from_mapping(
                    nested, ("uid", "user_id", "buyer_uid", "customer_uid")
                )
                if uid:
                    return uid

    content = context.content
    if isinstance(content, str):
        text = content.strip()
        if text.startswith("{"):
            try:
                content = json.loads(text)
            except json.JSONDecodeError:
                content = None
    if isinstance(content, dict):
        uid = _pick_from_mapping(
            content, ("buyer_uid", "uid", "user_id", "customer_uid")
        )
        if uid:
            return uid
        for key in ("from_uid", "to_uid"):
            s = str(content.get(key) or "").strip()
            if s and not _CS_UID_RE.match(s) and _DIGIT_UID_RE.match(s):
                return s

    return None


def format_transfer_system_preview(context: Context) -> str:
    """写入 chat_messages 的系统提示文案。"""
    from config import config

    custom = str(config.get("chat.inbound_transfer_system_notice") or "").strip()
    if custom:
        return custom

    content = context.content
    if isinstance(content, dict):
        parts = []
        for label, key in (("来自", "from_uid"), ("转至", "to_uid")):
            v = content.get(key)
            if v:
                parts.append(f"{label} {v}")
        if parts:
            return f"[会话已转接] {' · '.join(parts)}"
    return "[会话已转接] 售前/其他客服已将买家转给您，请关注后续消息"


def pick_transfer_cs_uid(
    cs_list: Dict[str, Any],
    shop_id: str,
    seller_user_id: str,
    *,
    exclude_self: bool = True,
) -> Optional[str]:
    """
    选择转接目标客服 cs_uid。
    优先 config.chat.preferred_transfer_seller_user_ids（售后专用子账号），否则按负载最低。
    """
    from config import config

    if not cs_list or not isinstance(cs_list, dict):
        return None

    my_cs = f"cs_{shop_id}_{seller_user_id}"
    preferred = config.get("chat.preferred_transfer_seller_user_ids") or []
    if not isinstance(preferred, list):
        preferred = [preferred]

    for entry in preferred:
        raw = str(entry or "").strip()
        if not raw:
            continue
        cs_key = raw if raw.startswith("cs_") else f"cs_{shop_id}_{raw}"
        if exclude_self and cs_key == my_cs:
            continue
        if cs_key not in cs_list:
            continue
        info = cs_list[cs_key] or {}
        if info.get("online", info.get("is_online", True)) is False:
            continue
        return cs_key

    from Agent.CustomerAgent.tools.move_conversation import _select_best_cs_uid

    return _select_best_cs_uid(cs_list, my_cs)
