"""
AI 回复触发本地人工协助：售后类问题且 AI 表示需产品经理跟进时转人工弹窗。
"""

from __future__ import annotations

from typing import Optional

from utils.after_sales_policy import is_after_sales_related

# AI 话术：表示无法自行处理、需产品经理介入（与 Agent 提示词一致）
_PM_ESCALATION_PHRASES = (
    "问问产品经理",
    "问产品经理",
    "跟产品经理",
    "产品经理确认",
    "产品经理回复",
    "稍后由产品经理",
    "产品同事确认",
    "跟产品确认",
)

# 货损/质量/错发等售后投诉（不一定含「退货」字样）
_DAMAGE_COMPLAINT_PHRASES = (
    "破损",
    "压坏",
    "压扁",
    "压变形",
    "压烂了",
    "碎了",
    "碎裂",
    "坏了",
    "损坏",
    "变形",
    "漏液",
    "漏了",
    "开裂",
    "裂痕",
    "少件",
    "缺件",
    "少发",
    "错发",
    "发错",
    "质量问题",
    "包装破",
    "包装盒",
    "盒子破",
    "快递压",
    "收到坏",
    "不能用",
    "有问题",
    "瑕疵",
    "烂了",
    "变形了",
    "缺货",
    "漏发",
)


def is_product_manager_escalation_reply(text: Optional[str]) -> bool:
    """AI 回复是否表示需产品经理跟进。"""
    t = (text or "").strip()
    if not t:
        return False
    return any(p in t for p in _PM_ESCALATION_PHRASES)


def is_after_sales_complaint_context(
    buyer_text: Optional[str],
    ai_reply: Optional[str] = None,
) -> bool:
    """买家诉求或上下文是否属于售后/货损类。"""
    buyer = (buyer_text or "").strip()
    if buyer and is_after_sales_related(buyer):
        return True
    combined = f"{buyer}\n{ai_reply or ''}"
    return any(p in combined for p in _DAMAGE_COMPLAINT_PHRASES)


def should_escalate_ai_pm_after_sales(
    buyer_text: Optional[str],
    ai_reply: Optional[str],
) -> bool:
    """AI 已用产品经理话术安抚且属于售后/货损 → 需本地人工弹窗。"""
    if not is_product_manager_escalation_reply(ai_reply):
        return False
    return is_after_sales_complaint_context(buyer_text, ai_reply)


def build_after_sales_pm_summary(
    buyer_text: Optional[str],
    ai_reply: Optional[str],
    *,
    max_buyer: int = 200,
    max_ai: int = 120,
) -> str:
    """组装弹窗摘要：买家诉求 + AI 已发话术。"""
    buyer = (buyer_text or "").strip()
    ai = (ai_reply or "").strip()
    if len(buyer) > max_buyer:
        buyer = buyer[:max_buyer] + "…"
    if len(ai) > max_ai:
        ai = ai[:max_ai] + "…"
    lines = []
    if buyer:
        lines.append(f"买家诉求：{buyer}")
    if ai:
        lines.append(f"AI 已回复：{ai}")
    return "\n".join(lines) if lines else "售后问题需人工跟进"
