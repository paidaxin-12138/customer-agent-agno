# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
from utils.ocr_content_filter import (
    filter_ocr_lines,
    filter_summary_markdown,
    looks_like_commerce_line,
)


def test_commerce_line_detection():
    assert looks_like_commerce_line("拼单价 ¥29.9")
    assert looks_like_commerce_line("库存：100")
    assert not looks_like_commerce_line("功率 48W")


def test_filter_ocr_lines():
    lines = ["功率 48W", "¥19.9", "USB充电"]
    assert filter_ocr_lines(lines) == ["功率 48W", "USB充电"]


def test_filter_summary_strips_price_bullets():
    md = "## 摘要\n\n- 功率48W\n- 价格¥29\n- 材质ABS"
    out = filter_summary_markdown(md)
    assert "48W" in out
    assert "¥29" not in out
