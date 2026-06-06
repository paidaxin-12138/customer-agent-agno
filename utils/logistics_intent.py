"""物流意图检测（从 Handler 抽离，供 intent_stage_reset 等复用）。"""
from __future__ import annotations

import re


def is_logistics_intent(text: str) -> bool:
    """询问包裹/物流进度（避免误伤闲聊）。"""
    t = (text or "").strip()
    if not t:
        return False
    strong = (
        "物流",
        "查物流",
        "快递到哪",
        "快递哪里",
        "快递呢",
        "发货了吗",
        "发货没",
        "发了吗",
        "揽收",
        "派送",
        "派件",
        "轨迹",
        "运单号",
        "运单",
        "到哪了",
        "到哪里了",
        "几天到",
        "什么时候到",
        "啥时候到",
        "单号",
        "快递单",
    )
    if any(s in t for s in strong):
        return True
    if "快递" in t and any(x in t for x in ("哪", "查", "单", "多久", "几天")):
        return True
    if re.search(r"(SF|YT|JD|ZTO|YTO|STO|EMS)\d{8,}", t, re.I):
        return True
    return False
