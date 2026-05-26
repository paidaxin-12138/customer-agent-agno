"""
三层会话记忆：短期原文 / 任务状态 / 长期摘要。

- 短期：最近 6–12 轮（可配置）原始消息，按时间正序
- 任务状态：当前意图、已填槽位、待确认字段、流程节点（持久化到 chat_sessions）
- 长期摘要：更早对话的事实摘要（用户诉求、已确认信息、未解决问题）
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from config import get_config
from utils.logger_loguru import get_logger

logger = get_logger("ConversationMemory")

_ROLE_TAG = {
    "customer": "买家",
    "ai": "客服(AI)",
    "human": "客服",
    "system": "系统",
}


@dataclass
class TaskState:
    """任务状态（会话级）。"""

    intent: str = "general"
    slots: Dict[str, str] = field(default_factory=dict)
    pending_confirm: List[str] = field(default_factory=list)
    flow_node: str = "general"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "TaskState":
        if not data:
            return cls()
        return cls(
            intent=str(data.get("intent") or "general"),
            slots=dict(data.get("slots") or {}),
            pending_confirm=list(data.get("pending_confirm") or []),
            flow_node=str(data.get("flow_node") or "general"),
        )


@dataclass
class LongTermSummary:
    """长期事实摘要。"""

    user_requests: List[str] = field(default_factory=list)
    confirmed: List[str] = field(default_factory=list)
    open_issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "LongTermSummary":
        if not data:
            return cls()
        return cls(
            user_requests=list(data.get("user_requests") or []),
            confirmed=list(data.get("confirmed") or []),
            open_issues=list(data.get("open_issues") or []),
        )

    def merge(self, other: "LongTermSummary") -> None:
        for lst, attr in (
            (self.user_requests, "user_requests"),
            (self.confirmed, "confirmed"),
            (self.open_issues, "open_issues"),
        ):
            cur = getattr(self, attr)
            for item in getattr(other, attr):
                s = str(item).strip()
                if s and s not in cur:
                    cur.append(s)
            setattr(self, attr, cur[-12:])


def _memory_cfg() -> Dict[str, Any]:
    enabled = get_config("chat.memory.enabled", True)
    rounds = get_config("chat.memory.short_term_rounds", 10)
    rmin = get_config("chat.memory.short_term_rounds_min", 6)
    rmax = get_config("chat.memory.short_term_rounds_max", 12)
    try:
        rounds = int(rounds)
        rmin = int(rmin)
        rmax = int(rmax)
    except (TypeError, ValueError):
        rounds, rmin, rmax = 10, 6, 12
    rounds = max(rmin, min(rmax, rounds))
    load = get_config("chat.memory.max_messages_load", 80)
    try:
        load = int(load)
    except (TypeError, ValueError):
        load = 80
    return {
        "enabled": bool(enabled),
        "short_term_rounds": rounds,
        "max_messages_load": max(40, load),
        "summarize_with_llm": bool(get_config("chat.memory.summarize_with_llm", False)),
    }


def _split_rounds(messages: List[Dict[str, Any]], max_rounds: int) -> Tuple[List[Dict], List[Dict]]:
    """
    按「买家发起的一轮」切分：一轮 = 从买家消息到下一买家消息前（含中间客服回复）。
    返回 (短期消息列表, 更早消息列表)，均为时间正序。
    """
    if not messages:
        return [], []

    rounds: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []

    for m in messages:
        role = str(m.get("sender_type") or "")
        if role == "customer" and current:
            rounds.append(current)
            current = []
        current.append(m)
    if current:
        rounds.append(current)

    if len(rounds) <= max_rounds:
        short = [msg for r in rounds for msg in r]
        return short, []

    short_rounds = rounds[-max_rounds:]
    old_rounds = rounds[:-max_rounds]
    short = [msg for r in short_rounds for msg in r]
    old = [msg for r in old_rounds for msg in r]
    return short, old


def _format_message_line(m: Dict[str, Any]) -> str:
    role = str(m.get("sender_type") or "")
    body = (m.get("content") or "").strip().replace("\n", " ")
    if len(body) > 400:
        body = body[:400] + "…"
    return f"{_ROLE_TAG.get(role, role)}：{body}"


def _extract_slots(text: str, slots: Dict[str, str]) -> None:
    t = text or ""
    for pat, key in [
        (r"(?:订单|单)号[：:\s]*([A-Za-z0-9\-]{6,})", "order_id"),
        (r"([0-9]{10,})", "order_id"),
        (r"(黑色|白色|粉色|红色|蓝色|绿色)", "color"),
        (r"(\d+[Ww])", "power"),
    ]:
        m = re.search(pat, t)
        if m and key not in slots:
            slots[key] = m.group(1)


def _infer_flow_node(intent: str, text: str, pending: List[str]) -> str:
    t = text or ""
    if pending:
        return "await_confirm"
    if intent == "logistics":
        return "logistics_flow"
    if intent == "after_sales":
        return "after_sales_flow"
    if intent in ("price", "product_spec"):
        return "product_flow"
    if any(k in t for k in ("转人工", "真人", "人工")):
        return "escalated"
    return "general"


def _guess_intent(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ("物流", "快递", "发货", "到哪")):
        return "logistics"
    if any(k in t for k in ("退", "换", "售后", "保修")):
        return "after_sales"
    if any(k in t for k in ("多少钱", "价格", "优惠")):
        return "price"
    if any(k in t for k in ("颜色", "款式", "规格", "参数")):
        return "product_spec"
    return "general"


def _update_task_state(
    state: TaskState,
    query: str,
    reply: str,
    intent: Optional[str] = None,
) -> TaskState:
    intent = intent or _guess_intent(query)
    state.intent = intent
    _extract_slots(query, state.slots)
    _extract_slots(reply, state.slots)

    pending: List[str] = []
    q = query or ""
    if "?" in q or "？" in q or any(k in q for k in ("吗", "是不是", "能不能", "可以吗")):
        if intent == "logistics":
            pending.append("物流/到货时间")
        elif intent == "product_spec":
            pending.append("商品规格/颜色")
    if any(k in q for k in ("地址", "电话", "收件人")) and "地址" not in state.slots:
        pending.append("收货信息")
    state.pending_confirm = pending[:5]
    state.flow_node = _infer_flow_node(intent, q, state.pending_confirm)
    return state


def _rule_summarize_messages(messages: List[Dict[str, Any]]) -> LongTermSummary:
    """从更早消息中提取事实摘要（规则版，不额外调 LLM）。"""
    out = LongTermSummary()
    for m in messages:
        role = str(m.get("sender_type") or "")
        body = (m.get("content") or "").strip()
        if not body or len(body) < 2:
            continue
        short = body[:120] + ("…" if len(body) > 120 else "")
        if role == "customer":
            out.user_requests.append(short)
            if any(k in body for k in ("退", "换", "投诉", "没收到", "坏了")):
                if short not in out.open_issues:
                    out.open_issues.append(short)
        elif role in ("ai", "human"):
            if any(k in body for k in ("确认", "已为您", "安排", "记录", "好的")):
                if short not in out.confirmed:
                    out.confirmed.append(short)
    out.user_requests = out.user_requests[-8:]
    out.confirmed = out.confirmed[-8:]
    out.open_issues = out.open_issues[-6:]
    return out


def _format_long_term(summary: LongTermSummary) -> str:
    if not (summary.user_requests or summary.confirmed or summary.open_issues):
        return ""
    lines = ["【长期摘要】（更早对话的事实，不含最近几轮原文）"]
    if summary.user_requests:
        lines.append("用户诉求：" + "；".join(summary.user_requests[-6:]))
    if summary.confirmed:
        lines.append("已确认信息：" + "；".join(summary.confirmed[-6:]))
    if summary.open_issues:
        lines.append("未解决问题：" + "；".join(summary.open_issues[-5:]))
    return "\n".join(lines)


def _format_task_state(state: TaskState) -> str:
    slots_s = "、".join(f"{k}={v}" for k, v in state.slots.items()) or "无"
    pending_s = "、".join(state.pending_confirm) or "无"
    return (
        "【任务状态】\n"
        f"- 当前意图：{state.intent}\n"
        f"- 已填槽位：{slots_s}\n"
        f"- 待确认字段：{pending_s}\n"
        f"- 当前流程节点：{state.flow_node}"
    )


def build_layered_prompt(
    query: str,
    context: Any,
    *,
    intent: Optional[str] = None,
) -> str:
    """
    组装三层记忆 + 本轮买家原话，供 CustomerAgent 使用。
    失败时回退为仅本轮 query。
    """
    q = (query or "").strip()
    cfg = _memory_cfg()
    if not cfg["enabled"] or context is None:
        return q

    if intent is None:
        try:
            from core.ops_telemetry import get_current_turn

            turn = get_current_turn()
            if turn and turn.intent:
                intent = str(turn.intent.get("label") or "")
        except Exception:
            pass

    try:
        from database.db_manager import db_manager

        ch = str(context.channel_type.value if context.channel_type else "pinduoduo")
        shop = str(getattr(context.kwargs, "shop_id", None) or "").strip()
        seller = str(getattr(context.kwargs, "user_id", None) or "").strip()
        buyer = str(getattr(context.kwargs, "from_uid", None) or "").strip()
        if not (shop and seller and buyer):
            return q
        acc = db_manager.get_account(ch, shop, seller)
        if not acc or not acc.get("id"):
            return q
        sess = db_manager.get_chat_session_by_buyer(int(acc["id"]), buyer, "active")
        if not sess:
            return q
        sid = int(sess["id"])

        mem = db_manager.get_session_memory(sid)
        task = TaskState.from_dict(
            json.loads(mem["task_state_json"]) if mem.get("task_state_json") else None
        )
        long_term = LongTermSummary.from_dict(
            json.loads(mem["long_term_summary"]) if mem.get("long_term_summary") else None
        )
        summary_through = int(mem.get("memory_summary_through_id") or 0)

        all_msgs = db_manager.get_chat_messages_recent(sid, limit=cfg["max_messages_load"])
        if not all_msgs:
            return q

        short_msgs, old_msgs = _split_rounds(all_msgs, cfg["short_term_rounds"])
        new_old = [m for m in old_msgs if int(m.get("id") or 0) > summary_through]
        if new_old:
            incremental = _rule_summarize_messages(new_old)
            long_term.merge(incremental)
            if old_msgs:
                summary_through = max(int(m.get("id") or 0) for m in old_msgs)

        _update_task_state(task, q, "", intent=intent)

        parts: List[str] = []
        lt_block = _format_long_term(long_term)
        if lt_block:
            parts.append(lt_block)
        parts.append(_format_task_state(task))
        if short_msgs:
            lines = [_format_message_line(m) for m in short_msgs]
            parts.append("【短期记忆】最近对话原文（按时间顺序）：\n" + "\n".join(lines))

        parts.append(
            "【语言匹配】检测买家语言并用相同语言回复。\n"
            "【回复要求】结合长期摘要与任务状态理解指代；短期原文优先；不要重复寒暄。\n"
            f"【本轮买家消息】\n{q}"
        )

        db_manager.update_session_memory(
            sid,
            task_state_json=json.dumps(task.to_dict(), ensure_ascii=False),
            long_term_summary=json.dumps(long_term.to_dict(), ensure_ascii=False),
            memory_summary_through_id=summary_through,
        )

        try:
            from core.ops_telemetry import set_coreference

            set_coreference(
                {
                    "memory_layers": ["long_term", "task_state", "short_term"],
                    "short_term_rounds": cfg["short_term_rounds"],
                    "short_term_message_count": len(short_msgs),
                    "has_long_term_summary": bool(lt_block),
                }
            )
        except Exception:
            pass

        return "\n\n".join(parts)
    except Exception as e:
        logger.debug(f"build_layered_prompt 失败: {e}")
        return q


def persist_turn_memory(
    context: Any,
    query: str,
    reply: str,
    *,
    intent: Optional[str] = None,
) -> None:
    """AI 回复成功后更新任务状态与长期摘要边界。"""
    cfg = _memory_cfg()
    if not cfg["enabled"] or not context:
        return
    try:
        from database.db_manager import db_manager

        shop = str(getattr(context.kwargs, "shop_id", None) or "").strip()
        seller = str(getattr(context.kwargs, "user_id", None) or "").strip()
        buyer = str(getattr(context.kwargs, "from_uid", None) or "").strip()
        ch = str(context.channel_type.value if context.channel_type else "pinduoduo")
        acc = db_manager.get_account(ch, shop, seller)
        if not acc:
            return
        sess = db_manager.get_chat_session_by_buyer(int(acc["id"]), buyer, "active")
        if not sess:
            return
        sid = int(sess["id"])
        mem = db_manager.get_session_memory(sid)
        task = TaskState.from_dict(
            json.loads(mem["task_state_json"]) if mem.get("task_state_json") else None
        )
        long_term = LongTermSummary.from_dict(
            json.loads(mem["long_term_summary"]) if mem.get("long_term_summary") else None
        )
        summary_through = int(mem.get("memory_summary_through_id") or 0)

        _update_task_state(task, query, reply, intent=intent)

        all_msgs = db_manager.get_chat_messages_recent(sid, limit=cfg["max_messages_load"])
        _, old_msgs = _split_rounds(all_msgs, cfg["short_term_rounds"])
        if old_msgs:
            summary_through = max(summary_through, max(int(m.get("id") or 0) for m in old_msgs))

        if reply and "暂未" in reply and "查" in reply:
            issue = (query or "")[:80]
            if issue and issue not in long_term.open_issues:
                long_term.open_issues.append(issue)

        db_manager.update_session_memory(
            sid,
            task_state_json=json.dumps(task.to_dict(), ensure_ascii=False),
            long_term_summary=json.dumps(long_term.to_dict(), ensure_ascii=False),
            memory_summary_through_id=summary_through,
        )
    except Exception as e:
        logger.debug(f"persist_turn_memory: {e}")
