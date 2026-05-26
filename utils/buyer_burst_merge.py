"""
买家在短时间内连发多条（甚至单字一条）时，从 DB 最近记录合并为一句，供 AI 整段理解。

避免只把「最后一个字」当成本轮输入而答偏、答空。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


def _parse_dt(row: Dict[str, Any]) -> Optional[datetime]:
    for k in ("sent_at", "created_at"):
        v = row.get(k)
        if isinstance(v, datetime):
            return v
    return None


def merge_trailing_buyer_burst(
    rows: List[Dict[str, Any]],
    *,
    gap_seconds: float = 45.0,
    max_parts: int = 40,
) -> str:
    """
    rows: 时间正序（与 db_manager.get_chat_messages_recent 一致：旧 → 新）。
    从最后一条买家消息起向前链式合并：仅当相邻两条均为 customer 且时间差 ≤ gap_seconds 时继续。
    """
    if not rows or gap_seconds <= 0:
        return ""
    n = len(rows)
    i = n - 1
    while i >= 0 and (rows[i].get("sender_type") or "") != "customer":
        i -= 1
    if i < 0:
        return ""

    # chain 先按「从新到旧」收集下标，再反转为旧→新拼接
    chain_new_to_old: List[int] = [i]
    cur = i
    while cur > 0:
        prev = cur - 1
        if (rows[prev].get("sender_type") or "") != "customer":
            break
        t_newer = _parse_dt(rows[cur])
        t_older = _parse_dt(rows[prev])
        if t_newer and t_older:
            try:
                delta = (t_newer - t_older).total_seconds()
            except Exception:
                delta = 0.0
            if delta > gap_seconds:
                break
        chain_new_to_old.append(prev)
        cur = prev
        if len(chain_new_to_old) >= max_parts:
            break

    chain_new_to_old.reverse()
    return "".join(str(rows[j].get("content") or "") for j in chain_new_to_old).strip()


def build_merged_buyer_query_for_ai(
    processed_fallback: str,
    context: Any,
    metadata: Dict[str, Any],
    *,
    gap_seconds: float,
    max_parts: int,
    recent_limit: int = 48,
) -> str:
    """
    解析当前账号/买家会话，读取最近消息并合并尾部买家 burst；失败则回退 processed_fallback。
    """
    try:
        from bridge.context import ContextType
        from database.db_manager import db_manager
        from ui.conversation_hub import parse_peer_from_context

        if getattr(context, "type", None) != ContextType.TEXT:
            return (processed_fallback or "").strip()

        ch = str(metadata.get("channel_name") or "pinduoduo")
        shop = str(metadata.get("shop_id") or "").strip()
        seller = str(metadata.get("user_id") or "").strip()
        buyer = str(metadata.get("from_uid") or "").strip()
        if not buyer:
            peer, _ = parse_peer_from_context(context)
            buyer = str(peer or "").strip()
        if not (shop and seller and buyer):
            return (processed_fallback or "").strip()

        acc = db_manager.get_account(ch, shop, seller)
        if not acc or not acc.get("id"):
            return (processed_fallback or "").strip()
        sid_row = db_manager.get_chat_session_by_buyer(int(acc["id"]), buyer, "active")
        if not sid_row:
            return (processed_fallback or "").strip()
        sid = int(sid_row["id"])
        rows = db_manager.get_chat_messages_recent(sid, limit=max(recent_limit, max_parts + 8))
        merged = merge_trailing_buyer_burst(
            rows, gap_seconds=gap_seconds, max_parts=max_parts
        )
        fb = (processed_fallback or "").strip()
        if not merged:
            return fb
        if fb and not merged.endswith(fb):
            merged = (merged + fb).strip()
        return merged
    except Exception:
        return (processed_fallback or "").strip()
