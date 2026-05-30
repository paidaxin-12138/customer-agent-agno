"""
OCR 文本清洗：剔除价格/库存等应由接口提供的字段，避免覆盖后台真实数据。
"""

from __future__ import annotations

import re
from typing import Iterable, List

# 单行疑似价格/促销/库存（用于 OCR 与 AI 摘要后处理）
_COMMERCE_LINE_PATTERNS = (
    re.compile(r"¥\s*[\d.,]+"),
    re.compile(r"[\d.,]+\s*元"),
    re.compile(r"拼单[价]?"),
    re.compile(r"券后"),
    re.compile(r"到手价"),
    re.compile(r"原价"),
    re.compile(r"现价"),
    re.compile(r"秒杀价"),
    re.compile(r"活动价"),
    re.compile(r"包邮价"),
    re.compile(r"库存\s*[:：]?\s*\d"),
    re.compile(r"仅剩\s*\d"),
    re.compile(r"已售\s*[\d.]+"),
    re.compile(r"SKU\s*ID", re.I),
    re.compile(r"^[\d.,]+\s*[-~～]\s*[\d.,]+\s*元?$"),
)


def looks_like_commerce_line(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if len(t) <= 12 and re.search(r"^[\d¥￥.,\s~-]+$", t):
        return True
    for pat in _COMMERCE_LINE_PATTERNS:
        if pat.search(t):
            return True
    return False


def filter_ocr_lines(lines: Iterable[str]) -> List[str]:
    out: List[str] = []
    for line in lines:
        t = (line or "").strip()
        if not t or looks_like_commerce_line(t):
            continue
        out.append(t)
    return out


def filter_ocr_text_block(text: str) -> str:
    if not text:
        return ""
    kept: List[str] = []
    for line in text.splitlines():
        t = line.strip()
        if not t:
            kept.append("")
            continue
        if t.startswith("【") and t.endswith("】"):
            kept.append(line)
            continue
        if looks_like_commerce_line(t):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def filter_summary_markdown(md: str) -> str:
    """从 LLM/规则摘要中移除价格、库存相关行。"""
    if not md:
        return ""
    out: List[str] = []
    for line in md.splitlines():
        stripped = line.strip()
        if not stripped:
            out.append(line)
            continue
        if stripped.startswith("#"):
            out.append(line)
            continue
        bullet = re.sub(r"^[-*•]\s*", "", stripped)
        if looks_like_commerce_line(bullet):
            continue
        out.append(line)
    return "\n".join(out).strip()
