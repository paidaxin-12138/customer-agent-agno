"""
买家转人工意图识别：精确短语 + 常见错别字 + 弱语义模式。

用于 KeywordDetectionHandler：「赚人工」「转人功」等也能触发弹窗与转接流程。
"""

from __future__ import annotations

import re
from typing import Optional

# 强匹配短语（含输入法/着急打错的常见变体）
_EXACT_PHRASES = (
    "转人工",
    "赚人工",
    "专人工",
    "砖人工",
    "轉人工",
    "转人功",
    "转人公",
    "赚人功",
    "人工客服",
    "真人客服",
    "转真人",
    "转客服",
    "换人工",
    "我要人工",
    "我找人工",
    "找人工",
    "接人工",
    "转接人工",
    "转接客服",
    "接入人工",
    "来个真人",
    "找真人",
    "要真人",
    "真人来",
    "人工处理",
    "人工服务",
    "转你们客服",
    "不要机器人",
    "别机器人",
    "不要ai",
    "真人说话",
    "有人吗",
    "有人在吗",
    "客服在吗",
    "客服呢",
    "能转接",
)

# 转/赚/专 + 人工|客服|真人；或明确索要真人/客服
_SEMANTIC_PATTERNS = (
    re.compile(r"[转赚专砖换叫接找要请让帮].{0,2}(?:人工|客服|真人)"),
    re.compile(r"转接.{0,2}(?:人工|客服|真人)"),
    re.compile(r"(?:有没有|有没).{0,2}(?:人工|真人|客服)"),
    # 仅「客服/人工在吗」类，不用宽泛的「人工…吗」以免误触「人工做的吗」
    re.compile(r"(?:人工|客服|真人)在(?:吗|嘛|呢|么?)"),
)

# 「手工制作」等商品语境，非转客服
_FALSE_POSITIVE_RE = re.compile(
    r"人工(?:做|制作|打造|缝制|生产|加工|的|版|丝|智能|合成|种植|造|活)"
    r"|纯手工|半人工|全人工|是人工的"
)

# 单字错别字：赚人、转人 + 工/功/公
_TYPO_RE = re.compile(r"[转赚专砖]人[工功公伍]")


def _prepare_text(text: str) -> str:
    """去掉常见前缀与空白，便于匹配「我：砖人工」「砖 人工」等。"""
    t = (text or "").strip()
    t = re.sub(r"^(我|买家|用户|客户)[:：]\s*", "", t, flags=re.I)
    return re.sub(r"\s+", "", t)


def detect_human_transfer_intent(text: Optional[str]) -> bool:
    """买家消息是否表达「要人工/真人客服」意图（含错别字）。"""
    raw = (text or "").strip()
    if not raw or len(raw) > 500:
        return False
    t = _prepare_text(raw)
    if not t:
        return False
    lower = t.lower()
    if any(p in t or p.lower() in lower for p in _EXACT_PHRASES):
        if _FALSE_POSITIVE_RE.search(t):
            return False
        return True
    if _TYPO_RE.search(t):
        return True
    if any(p.search(t) for p in _SEMANTIC_PATTERNS):
        if _FALSE_POSITIVE_RE.search(t):
            return False
        return True
    return False
