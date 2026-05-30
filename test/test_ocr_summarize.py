"""OCR 参数摘要（规则兜底）"""

from scripts.ocr_summarize import _rule_based_summary, summarize_ocr_for_knowledge


def test_rule_based_summary_picks_param_lines():
    text = "随机广告语\n功率 48W\n包邮到家"
    out = _rule_based_summary(text.splitlines(), "美甲灯")
    assert "48W" in out or "功率" in out


def test_summarize_without_llm_key():
    out = summarize_ocr_for_knowledge(
        "【主图1】电压 12V | 尺寸 20cm",
        goods_name="测试灯",
        use_llm=False,
    )
    assert "图文参数" in out or "12V" in out or "20cm" in out
