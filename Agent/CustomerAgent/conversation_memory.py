"""
三层会话记忆：短期原文 / 任务状态 / 长期摘要。

- 短期：最近 6–12 轮（可配置）原始消息，按时间正序
- 任务状态：当前意图、已填槽位、待确认字段、流程节点（持久化到 chat_sessions）
- 长期摘要：更早对话的事实摘要（用户诉求、已确认信息、未解决问题）
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from config import get_config
from Message.handlers.stage_constants import VALID_SESSION_STAGES
from utils.logger_loguru import get_logger

logger = get_logger("ConversationMemory")

# 历史数据曾把 intent（如 general/greeting）误写入 stage，导致 AI 门禁全拒
_LEGACY_STAGE_AS_IDLE: FrozenSet[str] = frozenset(
    {"general", "greeting", "human", "chat", ""}
)


def normalize_session_stage(stage: Optional[str]) -> str:
    """将非法/遗留 stage 规范为 idle，供 Handler 门禁与日志使用。"""
    st = (stage or "idle").strip() or "idle"
    if st in _LEGACY_STAGE_AS_IDLE or st not in VALID_SESSION_STAGES:
        return "idle"
    return st

# 会因超时自动回收为 idle 的业务 stage（不含 product_qa）
_STAGE_TIMEOUT_TARGETS = frozenset(
    {"address_change", "logistics", "after_sales", "await_confirm"}
)

_ROLE_TAG = {
    "customer": "买家",
    "ai": "客服(AI)",
    "human": "客服",
    "system": "系统",
}


@dataclass
class TaskState:
    """任务状态（会话级 SessionMemory）。"""

    intent: str = "general"
    last_intent: str = ""
    slots: Dict[str, str] = field(default_factory=dict)
    pending_confirm: List[str] = field(default_factory=list)
    stage: str = "idle"
    flow_node: str = "idle"
    stage_updated_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["flow_node"] = self.stage
        return d

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "TaskState":
        if not data:
            return cls()
        stage = normalize_session_stage(
            str(data.get("stage") or data.get("flow_node") or "idle")
        )
        raw_ts = data.get("stage_updated_at")
        try:
            stage_updated_at = float(raw_ts) if raw_ts is not None else 0.0
        except (TypeError, ValueError):
            stage_updated_at = 0.0
        return cls(
            intent=str(data.get("intent") or "general"),
            last_intent=str(data.get("last_intent") or ""),
            slots=dict(data.get("slots") or {}),
            pending_confirm=list(data.get("pending_confirm") or []),
            stage=stage,
            flow_node=stage,
            stage_updated_at=stage_updated_at,
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
    rounds = min(5, rounds)
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
    ts_raw = m.get("sent_at") or m.get("created_at")
    ts = ""
    if ts_raw is not None:
        try:
            from utils.chat_time import format_chat_iso

            ts = format_chat_iso(ts_raw)
        except Exception:
            ts = str(ts_raw)[:19]
    prefix = f"[{ts}] " if ts else ""
    return f"{prefix}{_ROLE_TAG.get(role, role)}：{body}"


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


def _infer_stage(intent: str, text: str, pending: List[str]) -> str:
    t = text or ""
    if pending:
        return "await_confirm"
    if intent == "logistics":
        return "logistics"
    if intent == "after_sales":
        return "after_sales"
    if intent in ("price", "product_spec", "general_product"):
        return "product_qa"
    if any(k in t for k in ("转人工", "真人", "人工")):
        return "human"
    return "idle"


def _guess_intent(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ("你好", "在吗", "您好", "早上好", "晚上好")):
        return "greeting"
    if any(k in t for k in ("物流", "快递", "发货", "到哪")):
        return "logistics"
    if any(k in t for k in ("退", "换", "售后", "保修")):
        return "after_sales"
    if any(k in t for k in ("多少钱", "价格", "优惠")):
        return "price"
    if any(k in t for k in ("颜色", "款式", "规格", "参数")):
        return "product_spec"
    if any(k in t for k in ("有没有", "有没", "有啥", "有什么", "哪款")):
        return "general_product"
    return "general"


def resolve_session_id(context: Any, metadata: Optional[Dict[str, Any]] = None) -> Optional[int]:
    """从 context / metadata 解析 chat_sessions.id。"""
    if context is None:
        return None
    try:
        from database.db_manager import db_manager

        meta = metadata or {}
        ch = str(
            meta.get("channel_name")
            or (context.channel_type.value if context.channel_type else "pinduoduo")
        )
        shop = str(meta.get("shop_id") or getattr(context.kwargs, "shop_id", None) or "").strip()
        seller = str(meta.get("user_id") or getattr(context.kwargs, "user_id", None) or "").strip()
        buyer = str(meta.get("from_uid") or getattr(context.kwargs, "from_uid", None) or "").strip()
        if not (shop and seller and buyer):
            return None
        acc = db_manager.get_account(ch, shop, seller)
        if not acc or not acc.get("id"):
            return None
        sess = db_manager.get_chat_session_by_buyer(int(acc["id"]), buyer, "active")
        if not sess:
            return None
        return int(sess["id"])
    except Exception as e:
        logger.debug(f"resolve_session_id: {e}")
        return None


def _stage_idle_timeout_sec() -> int:
    try:
        return int(get_config("retention.stage_idle_timeout_sec", 1800) or 1800)
    except (TypeError, ValueError):
        return 1800


def _touch_stage_timestamp(task: TaskState, new_stage: str) -> None:
    st = (new_stage or "idle").strip() or "idle"
    if st != (task.stage or "idle"):
        task.stage_updated_at = time.time()
    elif not task.stage_updated_at and st != "idle":
        task.stage_updated_at = time.time()


def maybe_expire_task_stage(task: TaskState) -> bool:
    """
    业务 stage 超过 retention.stage_idle_timeout_sec 则置 idle。
    返回是否发生了变更。
    """
    stage = (task.stage or "idle").strip() or "idle"
    if stage not in _STAGE_TIMEOUT_TARGETS:
        return False
    updated_at = float(task.stage_updated_at or 0)
    if updated_at <= 0:
        return False
    if time.time() - updated_at <= _stage_idle_timeout_sec():
        return False
    task.stage = "idle"
    task.flow_node = "idle"
    task.stage_updated_at = time.time()
    return True


def _persist_task_state_if_expired(session_id: int, task: TaskState) -> TaskState:
    normalized = normalize_session_stage(task.stage)
    if normalized != (task.stage or "idle"):
        task.stage = normalized
        task.flow_node = normalized
        update_session_state(
            session_id,
            stage=normalized,
            source_handler="StageNormalize",
        )
    if maybe_expire_task_stage(task):
        update_session_state(
            session_id,
            stage="idle",
            source_handler="StageTimeout",
        )
    return task


def get_current_stage(context: Any, metadata: Optional[Dict[str, Any]] = None) -> str:
    """读取当前会话 stage（优先 context.raw_data / metadata 缓存）。"""
    if metadata:
        cached = metadata.get("_session_stage")
        if cached is not None and str(cached).strip():
            return normalize_session_stage(str(cached))
    ku = getattr(context, "kwargs", None)
    if ku is not None:
        raw = getattr(ku, "raw_data", None) or {}
        if isinstance(raw, dict):
            cached = raw.get("_session_stage")
            if cached is not None and str(cached).strip():
                return normalize_session_stage(str(cached))
    sid = resolve_session_id(context, metadata)
    if sid is None:
        return "idle"
    task = load_task_state(sid)
    return normalize_session_stage(task.stage)


def prime_session_stage_on_context(
    context: Any, metadata: Optional[Dict[str, Any]] = None
) -> str:
    """在责任链执行前加载 stage（含超时回收）并写入 context/metadata。"""
    sid = resolve_session_id(context, metadata)
    if sid is not None:
        task = load_task_state(sid)
        stage = normalize_session_stage(task.stage)
    else:
        stage = get_current_stage(context, metadata)
    if metadata is not None:
        metadata["_session_stage"] = stage
    ku = getattr(context, "kwargs", None)
    if ku is not None:
        try:
            raw = dict(getattr(ku, "raw_data", None) or {})
            raw["_session_stage"] = stage
            if hasattr(ku, "raw_data"):
                ku.raw_data = raw
        except Exception as e:
            logger.debug(f"prime_session_stage_on_context: {e}")
    return stage


def load_task_state(session_id: int) -> TaskState:
    try:
        from database.db_manager import db_manager

        mem = db_manager.get_session_memory(session_id)
        raw = mem.get("task_state_json") if mem else None
        task = TaskState.from_dict(json.loads(raw) if raw else None)
        return _persist_task_state_if_expired(session_id, task)
    except Exception as e:
        logger.debug(f"load_task_state: {e}")
        return TaskState()


def update_session_state(
    session_id: int,
    *,
    intent: Optional[str] = None,
    last_intent: Optional[str] = None,
    slots: Optional[Dict[str, Any]] = None,
    stage: Optional[str] = None,
    pending_confirm: Optional[List[str]] = None,
    source_handler: str = "",
) -> TaskState:
    """读-改-写 task_state_json；slots 增量 merge。"""
    from database.db_manager import db_manager

    mem = db_manager.get_session_memory(session_id) or {}
    task = TaskState.from_dict(
        json.loads(mem["task_state_json"]) if mem.get("task_state_json") else None
    )
    if intent is not None:
        new_intent = str(intent).strip() or "general"
        if new_intent != task.intent and task.intent:
            task.last_intent = task.intent
        task.intent = new_intent
    if last_intent is not None:
        task.last_intent = str(last_intent).strip()
    if slots:
        for k, v in slots.items():
            if v is not None and str(v).strip():
                task.slots[str(k)] = str(v).strip()
    if stage is not None:
        st = str(stage).strip() or "idle"
        _touch_stage_timestamp(task, st)
        task.stage = st
        task.flow_node = st
    if pending_confirm is not None:
        task.pending_confirm = list(pending_confirm)
    ok = db_manager.update_session_memory(
        session_id,
        task_state_json=json.dumps(task.to_dict(), ensure_ascii=False),
    )
    if not ok:
        logger.warning(
            "update_session_state persist failed session={} handler={}",
            session_id,
            source_handler or "?",
        )
    if source_handler:
        logger.debug(
            "update_session_state session={} handler={} stage={} intent={} last_intent={} slot_keys={}",
            session_id,
            source_handler,
            task.stage,
            task.intent,
            task.last_intent,
            list(task.slots.keys()),
        )
    return task


def commit_handler_session_from_context(
    context: Any,
    metadata: Optional[Dict[str, Any]],
    *,
    stage: str,
    intent: Optional[str] = None,
    slots: Optional[Dict[str, Any]] = None,
    source_handler: str = "",
    release_stage: bool = False,
) -> None:
    sid = resolve_session_id(context, metadata)
    if sid is None:
        return
    effective_stage = "idle" if release_stage else stage
    update_session_state(
        sid,
        intent=intent,
        stage=effective_stage,
        slots=slots,
        source_handler=source_handler,
    )
    if metadata is not None:
        metadata["_session_stage"] = effective_stage
    ku = getattr(context, "kwargs", None)
    if ku is not None:
        try:
            raw = dict(getattr(ku, "raw_data", None) or {})
            raw["_session_stage"] = effective_stage
            if hasattr(ku, "raw_data"):
                ku.raw_data = raw
        except Exception as e:
            logger.debug(f"commit_handler_session_from_context cache: {e}")


def _compute_task_state_delta(
    state: TaskState,
    query: str,
    reply: str,
    intent: Optional[str] = None,
) -> Dict[str, Any]:
    """根据本轮 query/reply 计算 task_state 增量（不修改 state）。"""
    intent_val = intent or _guess_intent(query)
    delta: Dict[str, Any] = {"intent": intent_val}
    if intent_val != state.intent and state.intent:
        delta["last_intent"] = state.intent
    slot_updates: Dict[str, str] = {}
    tmp_slots = dict(state.slots)
    _extract_slots(query, tmp_slots)
    _extract_slots(reply, tmp_slots)
    for k, v in tmp_slots.items():
        if k not in state.slots or state.slots[k] != v:
            slot_updates[k] = v
    if slot_updates:
        delta["slots"] = slot_updates

    pending: List[str] = []
    q = query or ""
    if "?" in q or "？" in q or any(k in q for k in ("吗", "是不是", "能不能", "可以吗")):
        if intent_val == "logistics":
            pending.append("物流/到货时间")
        elif intent_val == "product_spec":
            pending.append("商品规格/颜色")
    if any(k in q for k in ("地址", "电话", "收件人")) and "address" not in tmp_slots:
        pending.append("收货信息")
    delta["pending_confirm"] = pending[:5]

    inferred = _infer_stage(intent_val, q, pending[:5])
    cur_stage = (state.stage or "idle").strip() or "idle"
    if cur_stage in ("idle", "general", "") or inferred != "idle":
        if inferred != cur_stage:
            delta["stage"] = inferred
    return delta


def _apply_task_state_delta(state: TaskState, delta: Dict[str, Any]) -> TaskState:
    """将 delta 应用到内存 TaskState（不写库）。"""
    if "intent" in delta:
        new_intent = str(delta["intent"]).strip() or "general"
        if new_intent != state.intent and state.intent and "last_intent" not in delta:
            state.last_intent = state.intent
        state.intent = new_intent
    if "last_intent" in delta:
        state.last_intent = str(delta["last_intent"]).strip()
    for k, v in (delta.get("slots") or {}).items():
        if v is not None and str(v).strip():
            state.slots[str(k)] = str(v).strip()
    if "pending_confirm" in delta:
        state.pending_confirm = list(delta["pending_confirm"])
    if "stage" in delta:
        st = str(delta["stage"]).strip() or "idle"
        _touch_stage_timestamp(state, st)
        state.stage = st
        state.flow_node = st
    return state


def _update_task_state(
    state: TaskState,
    query: str,
    reply: str,
    intent: Optional[str] = None,
) -> TaskState:
    delta = _compute_task_state_delta(state, query, reply, intent=intent)
    return _apply_task_state_delta(state, delta)


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


def _format_current_flow(state: TaskState) -> str:
    slots_json = json.dumps(state.slots, ensure_ascii=False) if state.slots else "{}"
    return f"【当前流程】stage={state.stage}, slots={slots_json}"


def _format_task_state(state: TaskState) -> str:
    slots_s = "、".join(f"{k}={v}" for k, v in state.slots.items()) or "无"
    pending_s = "、".join(state.pending_confirm) or "无"
    last_s = state.last_intent or "无"
    return (
        "【任务状态】\n"
        f"- 当前意图：{state.intent}\n"
        f"- 上轮意图：{last_s}\n"
        f"- 已填槽位：{slots_s}\n"
        f"- 待确认字段：{pending_s}\n"
        f"- 当前阶段：{state.stage}"
    )


def build_layered_prompt(
    query: str,
    context: Any,
    *,
    intent: Optional[str] = None,
    read_only: bool = True,
) -> str:
    """
    组装三层记忆 + 本轮买家原话，供 CustomerAgent 使用。
    read_only=True 时仅读取/内存推演 task_state，不写库（持久化由 persist_turn_memory / Handler 负责）。
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

        delta = _compute_task_state_delta(task, q, "", intent=intent)
        _apply_task_state_delta(task, delta)

        parts: List[str] = []
        parts.append(_format_current_flow(task))
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
        try:
            ku = getattr(context, "kwargs", None)
            raw_ts = getattr(ku, "timestamp", None) if ku else None
            if raw_ts is not None:
                from utils.chat_time import (
                    format_chat_iso,
                    naive_shanghai_from_unix_ts,
                )

                ts_val = naive_shanghai_from_unix_ts(float(raw_ts) / 1000.0)
                parts.append(f"【本轮消息时间】{format_chat_iso(ts_val)}")
        except Exception:
            pass

        if not read_only:
            update_session_state(
                sid,
                intent=task.intent,
                last_intent=task.last_intent or None,
                slots=task.slots or None,
                stage=task.stage,
                pending_confirm=task.pending_confirm,
                source_handler="build_layered_prompt",
            )
            db_manager.update_session_memory(
                sid,
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

        intent_label = intent or _guess_intent(query)
        delta = _compute_task_state_delta(task, query, reply, intent=intent_label)
        _apply_task_state_delta(task, delta)

        all_msgs = db_manager.get_chat_messages_recent(sid, limit=cfg["max_messages_load"])
        _, old_msgs = _split_rounds(all_msgs, cfg["short_term_rounds"])
        if old_msgs:
            summary_through = max(summary_through, max(int(m.get("id") or 0) for m in old_msgs))

        if reply and "暂未" in reply and "查" in reply:
            issue = (query or "")[:80]
            if issue and issue not in long_term.open_issues:
                long_term.open_issues.append(issue)

        product_intents = {"product_spec", "price", "general_product"}
        ai_stage = "product_qa" if intent_label in product_intents else task.stage
        update_session_state(
            sid,
            intent=intent_label,
            stage=ai_stage,
            slots=task.slots or None,
            pending_confirm=task.pending_confirm,
            source_handler="AIReplyHandler",
        )
        db_manager.update_session_memory(
            sid,
            long_term_summary=json.dumps(long_term.to_dict(), ensure_ascii=False),
            memory_summary_through_id=summary_through,
        )
    except Exception as e:
        logger.debug(f"persist_turn_memory: {e}")
