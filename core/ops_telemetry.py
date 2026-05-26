"""
运营看板数据采集：链路追踪、成本、低置信度、安全审计。
"""

from __future__ import annotations

import json
import re
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger_loguru import get_logger

logger = get_logger("OpsTelemetry")

_SENSITIVE_PATTERNS = [
    r"密码|password|api[_-]?key|secret|token|身份证|银行卡",
    r"转人工|真人客服|投诉|举报",
]


@dataclass
class TurnTrace:
    trace_id: str
    session_key: str = ""
    user_label: str = ""
    channel: str = "pinduoduo"
    query_text: str = ""
    coreference: Dict[str, Any] = field(default_factory=dict)
    intent: Dict[str, Any] = field(default_factory=dict)
    rewrite: Dict[str, Any] = field(default_factory=dict)
    recall: List[Dict[str, Any]] = field(default_factory=list)
    rerank: List[Dict[str, Any]] = field(default_factory=list)
    final_answer: str = ""


_current_turn: ContextVar[Optional[TurnTrace]] = ContextVar("ops_current_turn", default=None)


def start_turn(
    query: str,
    *,
    session_key: str = "",
    user_label: str = "",
    channel: str = "pinduoduo",
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """开始一次 AI 处理链路。"""
    meta = metadata or {}
    trace = TurnTrace(
        trace_id=str(uuid.uuid4()),
        session_key=session_key or str(meta.get("user_key") or ""),
        user_label=user_label or str(meta.get("username") or meta.get("from_uid") or ""),
        channel=channel or str(meta.get("channel_name") or "pinduoduo"),
        query_text=(query or "").strip(),
    )
    trace.rewrite = {"original": trace.query_text, "merged": trace.query_text}
    _current_turn.set(trace)
    scan_security(trace.query_text, trace.user_label, event_type="buyer_message")
    return trace.trace_id


def get_current_turn() -> Optional[TurnTrace]:
    return _current_turn.get()


def set_coreference(data: Dict[str, Any]) -> None:
    t = _current_turn.get()
    if t:
        t.coreference = data


def set_intent(intent: str, confidence: float = 0.0, extra: Optional[Dict] = None) -> None:
    t = _current_turn.get()
    if t:
        t.intent = {"label": intent, "confidence": confidence, **(extra or {})}


def set_rewrite(rewritten: str) -> None:
    t = _current_turn.get()
    if t:
        t.rewrite = {**(t.rewrite or {}), "rewritten": rewritten}


def _hit_score(h: Any, rank_index: int) -> float:
    """优先用检索器写入的 rerank_score，否则按排序位置递减。"""
    meta: Dict[str, Any] = {}
    if hasattr(h, "metadata") and isinstance(getattr(h, "metadata", None), dict):
        meta = getattr(h, "metadata") or {}
    elif isinstance(h, dict):
        meta = h.get("metadata") or {}
    raw = meta.get("rerank_score")
    if raw is not None:
        try:
            return round(float(raw), 4)
        except (TypeError, ValueError):
            pass
    return round(max(0.05, 1.0 - rank_index * 0.05), 4)


def set_recall_results(hits: List[Any]) -> None:
    t = _current_turn.get()
    if not t:
        return
    recall: List[Dict[str, Any]] = []
    rerank: List[Dict[str, Any]] = []
    for i, h in enumerate(hits or []):
        if hasattr(h, "id"):
            meta = dict(getattr(h, "metadata", None) or {})
            content = str(getattr(h, "data", "") or "")[:500]
            doc_id = str(getattr(h, "id", ""))
        elif isinstance(h, dict):
            meta = dict(h.get("metadata") or {})
            content = str(h.get("content", ""))[:500]
            doc_id = str(h.get("id", ""))
        else:
            continue
        score = _hit_score(h, i)
        recall.append({"id": doc_id, "snippet": content, "meta": meta})
        rerank.append(
            {
                "id": doc_id,
                "score": score,
                "vector_distance": meta.get("vector_distance"),
            }
        )
    t.recall = recall
    t.rerank = rerank
    if not recall:
        try:
            from database.ops_repository import get_ops_repository

            get_ops_repository().upsert_low_confidence(
                t.query_text, channel=t.channel
            )
        except Exception as e:
            logger.debug(f"low_confidence upsert skipped: {e}")


def enrich_from_agent_input(
    original_query: str,
    enriched_input: str,
    *,
    transcript_lines: int = 0,
) -> None:
    """记录查询改写与指代消解（来自 CustomerAgent 实际上下文组装）。"""
    t = _current_turn.get()
    if not t:
        return
    orig = (original_query or "").strip()
    enriched = (enriched_input or "").strip()
    t.rewrite = {
        "original": orig,
        "merged": t.rewrite.get("merged") if isinstance(t.rewrite, dict) else orig,
        "enriched_with_transcript": enriched,
        "was_expanded": len(enriched) > len(orig) + 20,
    }
    t.coreference = {
        "transcript_lines": transcript_lines,
        "uses_session_history": transcript_lines > 0,
        "note": "从 SQLite 最近消息拼入上下文，供 LLM 理解「这个/那款」等指代",
    }


def record_llm_usage(run_output: Any, *, model_name: str = "") -> None:
    """从 Agno RunOutput 读取真实 token（若有），写入成本看板。"""
    t = _current_turn.get()
    if not t:
        return
    prompt_tokens = 0
    completion_tokens = 0
    try:
        metrics = getattr(run_output, "metrics", None)
        if metrics is not None:
            prompt_tokens = int(
                getattr(metrics, "input_tokens", 0)
                or getattr(metrics, "prompt_tokens", 0)
                or 0
            )
            completion_tokens = int(
                getattr(metrics, "output_tokens", 0)
                or getattr(metrics, "completion_tokens", 0)
                or 0
            )
    except Exception:
        pass
    try:
        from config import get_config
        from database.ops_repository import get_ops_repository

        model = model_name or get_config("llm.model_name", "unknown")
        if prompt_tokens <= 0 and completion_tokens <= 0:
            q_len = len(t.query_text or "")
            a_len = len(t.final_answer or t.query_text or "")
            prompt_tokens = max(1, q_len // 2)
            completion_tokens = max(1, a_len // 2)
        cost = (prompt_tokens + completion_tokens) * 0.000002
        get_ops_repository().insert_cost(
            {
                "session_key": t.session_key,
                "model_name": model,
                "call_count": 1,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cache_hit": bool(t.recall),
                "cost_usd": cost,
            }
        )
    except Exception as e:
        logger.debug(f"record_llm_usage: {e}")


def finish_turn(final_answer: str, *, intent_label: str = "general") -> None:
    """持久化链路并写入成本估算。"""
    t = _current_turn.get()
    if not t:
        return
    t.final_answer = (final_answer or "").strip()
    if not t.intent:
        t.intent = {"label": intent_label, "confidence": 0.0}
    scan_security(t.final_answer, t.user_label, event_type="ai_reply")
    try:
        from database.ops_repository import get_ops_repository

        repo = get_ops_repository()
        repo.insert_trace(
            {
                "trace_id": t.trace_id,
                "session_key": t.session_key,
                "user_label": t.user_label,
                "channel": t.channel,
                "query_text": t.query_text,
                "coreference_json": json.dumps(t.coreference, ensure_ascii=False),
                "intent_json": json.dumps(t.intent, ensure_ascii=False),
                "rewrite_json": json.dumps(t.rewrite, ensure_ascii=False),
                "recall_json": json.dumps(t.recall, ensure_ascii=False),
                "rerank_json": json.dumps(t.rerank, ensure_ascii=False),
                "final_answer": t.final_answer,
            }
        )
        intent_label = (t.intent or {}).get("label") or intent_label
        try:
            repo.update_session_intent(t.session_key, t.user_label, intent_label)
        except Exception:
            pass
        if not t.recall and t.query_text:
            repo.create_ticket(
                title=f"低置信度待处理: {(t.query_text[:40] + '…') if len(t.query_text) > 40 else t.query_text}",
                source="ai",
                session_key=t.session_key,
                payload={"trace_id": t.trace_id, "reason": "no_knowledge_hit"},
            )
    except Exception as e:
        logger.warning(f"finish_turn persist failed: {e}")
    finally:
        _current_turn.set(None)


def scan_security(text: str, user_label: str = "", event_type: str = "message") -> None:
    if not text:
        return
    for pat in _SENSITIVE_PATTERNS:
        if re.search(pat, text, re.I):
            try:
                from database.ops_repository import get_ops_repository

                get_ops_repository().insert_security_audit(
                    {
                        "event_type": event_type,
                        "detail": text[:500],
                        "user_label": user_label,
                        "severity": "warn" if "转人工" in text else "info",
                    }
                )
            except Exception:
                pass
            break


def record_human_transfer(session_key: str, user_label: str, reason: str = "") -> None:
    try:
        from database.ops_repository import get_ops_repository

        repo = get_ops_repository()
        repo.insert_security_audit(
            {
                "event_type": "transfer_human",
                "detail": reason or "关键词/人工协助",
                "user_label": user_label,
                "severity": "info",
            }
        )
        repo.create_ticket(
            title=f"转人工 {user_label or session_key}",
            source="human",
            session_key=session_key,
            payload={"reason": reason},
        )
        repo.sync_sessions_from_chat()
    except Exception as e:
        logger.debug(f"record_human_transfer: {e}")


def record_tool_call(tool_name: str, detail: str, user_label: str = "") -> None:
    try:
        from database.ops_repository import get_ops_repository

        get_ops_repository().insert_security_audit(
            {
                "event_type": "tool_call",
                "detail": f"{tool_name}: {detail[:400]}",
                "user_label": user_label,
                "severity": "info",
                "payload_json": json.dumps({"tool": tool_name}, ensure_ascii=False),
            }
        )
    except Exception:
        pass
