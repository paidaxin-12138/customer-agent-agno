"""
合并会话中尚未被 AI/人工回复的买家消息，供 LLM 一次性作答。

「未回复」= 出现在最后一条有效出站回复（ai/human，不含平台文明提示）之后的买家消息。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from utils.platform_system_msg import is_platform_civility_content


def _is_platform_civility_row(row: Dict[str, Any]) -> bool:
    if (row.get("sender_type") or "") == "system":
        return is_platform_civility_content(row.get("content"))
    if (row.get("sender_type") or "") == "human":
        return is_platform_civility_content(row.get("content"))
    return False


def _is_effective_reply_row(row: Dict[str, Any]) -> bool:
    st = row.get("sender_type") or ""
    if st not in ("ai", "human"):
        return False
    return not _is_platform_civility_row(row)


def collect_unreplied_buyer_messages(
    rows: List[Dict[str, Any]],
    *,
    max_scan: int = 5,
    max_parts: int = 3,
) -> List[str]:
    """
    rows: 时间正序（旧→新）。从末尾向前找最近 max_scan 条买家消息，
    取最后一条有效回复之后的买家内容，最多 max_parts 条。
    """
    if not rows:
        return []

    last_reply_idx = -1
    for i in range(len(rows) - 1, -1, -1):
        if _is_effective_reply_row(rows[i]):
            last_reply_idx = i
            break

    buyer_after: List[str] = []
    scanned = 0
    for i in range(len(rows) - 1, last_reply_idx, -1):
        row = rows[i]
        if (row.get("sender_type") or "") != "customer":
            continue
        scanned += 1
        if scanned > max_scan:
            break
        body = str(row.get("content") or "").strip()
        if body:
            buyer_after.append(body)

    buyer_after.reverse()
    if len(buyer_after) > max_parts:
        buyer_after = buyer_after[-max_parts:]
    return buyer_after


def merge_unreplied_parts(parts: List[str], *, max_chars: int = 2000) -> str:
    if not parts:
        return ""
    working = list(parts)
    while working:
        if len(working) == 1:
            out = working[0]
        else:
            lines = [f"用户先问：{working[0]}"]
            for p in working[1:-1]:
                lines.append(f"然后问：{p}")
            lines.append(f"然后问：{working[-1]}")
            lines.append("请一并回答。")
            out = "\n".join(lines)
        if len(out) <= max_chars:
            return out
        if len(working) == 1:
            return out[: max_chars - 1] + "…"
        working = working[1:]
    return ""


def get_unreplied_buyer_messages(
    session_id: int,
    max_count: int = 3,
    *,
    max_scan: int = 5,
    recent_limit: int = 40,
) -> List[str]:
    """
    取 session 最近消息，返回最后一条有效客服回复之后的未回复买家消息（升序，最多 max_count 条）。
    平台文明提示不计为有效回复。
    """
    try:
        from database.db_manager import db_manager

        rows = db_manager.get_chat_messages_recent(
            int(session_id),
            limit=max(recent_limit, max_scan + max_count + 10),
        )
        return collect_unreplied_buyer_messages(
            rows, max_scan=max_scan, max_parts=max(1, max_count)
        )
    except Exception:
        return []


def build_unreplied_buyer_query_for_ai(
    processed_fallback: str,
    context: Any,
    metadata: Dict[str, Any],
    *,
    max_scan: int = 5,
    max_parts: int = 3,
    max_chars: int = 2000,
    recent_limit: int = 40,
) -> str:
    """读取 DB 最近消息，合并未回复买家提问；失败则回退 processed_fallback。"""
    fb = (processed_fallback or "").strip()
    try:
        from database.db_manager import db_manager
        from ui.conversation_hub import parse_peer_from_context

        ch = str(metadata.get("channel_name") or "pinduoduo")
        shop = str(metadata.get("shop_id") or "").strip()
        seller = str(metadata.get("user_id") or "").strip()
        buyer = str(metadata.get("from_uid") or "").strip()
        if not buyer:
            peer, _ = parse_peer_from_context(context)
            buyer = str(peer or "").strip()
        if not (shop and seller and buyer):
            return fb

        acc = db_manager.get_account(ch, shop, seller)
        if not acc or not acc.get("id"):
            return fb
        sid_row = db_manager.get_chat_session_by_buyer(int(acc["id"]), buyer, "active")
        if not sid_row:
            return fb
        sid = int(sid_row["id"])
        parts = get_unreplied_buyer_messages(
            sid,
            max_count=max_parts,
            max_scan=max_scan,
            recent_limit=max(recent_limit, max_scan + max_parts + 10),
        )
        merged = merge_unreplied_parts(parts, max_chars=max_chars)
        if not merged:
            return fb
        return merged
    except Exception:
        return fb
