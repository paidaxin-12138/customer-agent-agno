"""LLM 兜底话术替换。"""
from utils.llm_errors import sanitize_ai_reply_content, should_replace_pm_fallback_reply


def test_replace_pm_reply_by_default():
    assert should_replace_pm_fallback_reply("我去问问产品经理确认下")
    out = sanitize_ai_reply_content("我去问问产品经理确认下")
    assert "产品经理" not in out
    assert "暂时还不清楚" in out


def test_keep_normal_reply():
    text = "这款有现货哦亲亲"
    assert sanitize_ai_reply_content(text) == text
