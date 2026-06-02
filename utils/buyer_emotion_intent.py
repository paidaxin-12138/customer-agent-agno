"""买家消息情绪波动检测（关键词 + 语义片段）。"""
from __future__ import annotations

from typing import Optional

# 愤怒、不满、催促、投诉类表达（与转人工关键词部分重叠，专用于情绪预警）
_EMOTION_PHRASES = (
    "气死",
    "生气",
    "愤怒",
    "火大",
    "受不了",
    "什么态度",
    "态度太差",
    "态度差",
    "垃圾",
    "骗子",
    "诈骗",
    "差评",
    "投诉",
    "举报",
    "坑人",
    "坑死了",
    "太差了",
    "太烂了",
    "烂货",
    "搞什么",
    "有没有搞错",
    "怎么回事",
    "等久了",
    "等太久",
    "还不发",
    "催死了",
    "急死了",
    "无语",
    "离谱",
    "骗我",
    "欺骗",
    "不满意",
    "非常不满",
    "太过分",
    "欺负人",
    "糊弄",
    "敷衍",
)


def detect_buyer_emotion(text: Optional[str]) -> bool:
    """买家文本是否呈现明显负面情绪/催促/投诉倾向。"""
    t = (text or "").strip()
    if not t or len(t) < 2:
        return False
    tl = t.lower()
    return any(p in tl for p in _EMOTION_PHRASES)


def build_emotion_alert_summary(
    buyer_text: Optional[str],
    *,
    buyer_nickname: str = "买家",
    max_len: int = 2000,
) -> str:
    """组装情绪预警弹窗摘要。"""
    nick = (buyer_nickname or "买家").strip()
    msg = (buyer_text or "").strip()
    if len(msg) > max_len:
        msg = msg[:max_len] + "…"
    head = f"监测到买家「{nick}」有情绪波动"
    if msg:
        return f"{head}\n\n买家原话：{msg}"
    return head
