"""弱高风险买家消息：累计达阈值后代码直转（不降级走 AI / 排队）。"""
from __future__ import annotations

import re
from threading import Lock
from typing import Dict, Optional, Pattern, Tuple

from config import config

_lock = Lock()
_counts: Dict[str, int] = {}

_WEAK_HIGH_RISK_PHRASES: Tuple[str, ...] = (
    "过敏",
    "红肿",
    "发痒",
    "起疹",
    "起泡",
    "烂脸",
    "烧伤",
    "身体不适",
    "不舒服",
    "去医院",
    "投诉",
    "举报",
    "工商",
    "315",
    "消协",
    "律师",
    "起诉",
    "赔偿",
    "索赔",
    "医药费",
    "骗人",
    "诈骗",
    "假货",
    "三无",
    "不退款",
    "退款不给",
    "拒退",
    "没效果",
    "没有用",
    "纠纷",
    "维权",
)

_WEAK_HIGH_RISK_PATTERNS: Tuple[Pattern[str], ...] = (
    re.compile(r"用了.{0,12}(?:过敏|红肿|发痒|起疹)"),
    re.compile(r"(?:产品|东西|灯).{0,8}(?:过敏|红肿|痒)"),
    re.compile(r"(?:要求|要).{0,6}(?:赔偿|索赔|退款)"),
)


def _prepare_text(text: Optional[str]) -> str:
    t = (text or "").strip()
    t = re.sub(r"^(我|买家|用户|客户)[:：]\s*", "", t, flags=re.I)
    return re.sub(r"\s+", "", t)


def detect_weak_high_risk_text(text: Optional[str]) -> bool:
    """仅靠文字难以安全处理、但未命中关键词表时的弱高风险信号。"""
    raw = (text or "").strip()
    if not raw or len(raw) > 500:
        return False
    t = _prepare_text(raw)
    if not t:
        return False
    lower = t.lower()
    if any(p in t or p.lower() in lower for p in _WEAK_HIGH_RISK_PHRASES):
        return True
    return any(p.search(t) for p in _WEAK_HIGH_RISK_PATTERNS)


def record_weak_high_risk(session_key: str, text: Optional[str]) -> int:
    """记录一次弱高风险；非弱高风险不计数。返回当前累计次数。"""
    if not detect_weak_high_risk_text(text):
        return get_weak_high_risk_count(session_key)
    key = (session_key or "").strip()
    if not key:
        return 1
    with _lock:
        n = _counts.get(key, 0) + 1
        _counts[key] = n
        return n


def get_weak_high_risk_count(session_key: str) -> int:
    key = (session_key or "").strip()
    if not key:
        return 0
    with _lock:
        return _counts.get(key, 0)


def reset_weak_high_risk(session_key: str) -> None:
    key = (session_key or "").strip()
    if not key:
        return
    with _lock:
        _counts.pop(key, None)


def should_direct_transfer_second_weak(
    session_key: Optional[str],
    text: Optional[str],
) -> bool:
    """
    第二次（可配置）弱高风险：不走排队降级 / LLM，改代码直转。
    """
    if not bool(config.get("chat.high_risk_second_turn_enabled", True)):
        return False
    try:
        threshold = int(config.get("chat.high_risk_second_turn_threshold", 2) or 2)
    except (TypeError, ValueError):
        threshold = 2
    threshold = max(1, min(threshold, 5))
    count = record_weak_high_risk(session_key or "", text)
    return count >= threshold
