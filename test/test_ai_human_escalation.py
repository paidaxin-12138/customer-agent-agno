"""AI 售后 + 产品经理话术 → 转人工弹窗判定"""

from utils.ai_human_escalation import (
    build_after_sales_pm_summary,
    is_after_sales_complaint_context,
    is_product_manager_escalation_reply,
    should_escalate_ai_pm_after_sales,
)


def test_pm_reply_detected():
    assert is_product_manager_escalation_reply("亲亲，我去问问产品经理确认下~")
    assert not is_product_manager_escalation_reply("这款有现货哦亲亲")


def test_damage_complaint_context():
    assert is_after_sales_complaint_context("包装盒破损，商品被压坏了")
    assert is_after_sales_complaint_context("想退货退款")
    assert not is_after_sales_complaint_context("有没有白色款")


def test_should_escalate_after_sales_pm():
    buyer = "收到快递盒子破了，灯也压坏了"
    ai = "非常抱歉亲亲，这边跟产品经理确认下，稍后回复您"
    assert should_escalate_ai_pm_after_sales(buyer, ai)


def test_should_not_escalate_non_after_sales():
    buyer = "有没有打磨机"
    ai = "知识库暂未收录，我去问问产品经理"
    assert not should_escalate_ai_pm_after_sales(buyer, ai)


def test_build_summary():
    text = build_after_sales_pm_summary(
        "包装盒破损",
        "我去问问产品经理确认下",
    )
    assert "买家诉求" in text
    assert "AI 已回复" in text
