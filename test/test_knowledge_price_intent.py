"""价格比较意图：避免「最贵的呢」误套通用价格区间 FAQ。"""

from __future__ import annotations

from Agent.CustomerAgent.agent_knowledge import get_knowledge_manager


def test_most_expensive_not_price_range_faq():
    mgr = get_knowledge_manager()
    reply = mgr.answer_question("最贵的呢")
    assert "价格区间是" not in reply
    assert "SUN X5 Plus" in reply or "X5 Plus" in reply
    assert "13.93" in reply


def test_cheapest_returns_lowest_price_product():
    mgr = get_knowledge_manager()
    reply = mgr.answer_question("最便宜的是哪款")
    assert "价格区间是" not in reply
    assert "3.99" in reply or "迷你" in reply


def test_generic_price_faq_still_works():
    mgr = get_knowledge_manager()
    reply = mgr.answer_question("你们美甲灯多少钱")
    assert "价格" in reply
