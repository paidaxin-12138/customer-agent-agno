"""
将 OCR 原文整理为知识库可用的商品参数摘要（优先 LLM，失败则规则兜底）。
严禁输出价格/库存，避免覆盖接口数据。
"""

from __future__ import annotations

import re
from typing import List, Optional

from config import get_config
from utils.logger_loguru import get_logger
from utils.ocr_content_filter import filter_ocr_lines, filter_summary_markdown, looks_like_commerce_line

logger = get_logger("OCRSummarize")

_PARAM_HINTS = (
    "功率", "瓦", "W", "电压", "V", "尺寸", "规格", "容量", "重量", "材质",
    "灯珠", "定时", "波长", "nm", "USB", "充电", "电池", "续航", "颜色",
    "款式", "型号", "认证", "CE", "FCC", "质保", "保修", "套餐", "配件",
    "功能", "档位", "模式", "温度", "℃",
)


def _rule_based_summary(ocr_lines: List[str], goods_name: str = "") -> str:
    """无 LLM 时从 OCR 行中提取疑似参数行（不含价格）。"""
    lines = filter_ocr_lines(ocr_lines)
    bullets: List[str] = []
    seen: set[str] = set()
    for line in lines:
        t = (line or "").strip()
        if len(t) < 2 or t in seen:
            continue
        if any(h in t for h in _PARAM_HINTS) or re.search(
            r"\d+\s*(W|w|V|v|cm|mm|ml|g|kg|°)", t
        ):
            seen.add(t)
            bullets.append(t)
    if not bullets:
        compact = [ln.strip() for ln in lines if len((ln or "").strip()) >= 2][:15]
        if not compact:
            return ""
        bullets = compact

    title = (goods_name or "商品").strip()[:80]
    out = ["### 图文参数摘要（规则提取，不含价格）", ""]
    if title:
        out.append(f"关联商品：{title}")
        out.append("")
    for b in bullets[:25]:
        out.append(f"- {b}")
    return "\n".join(out)


def summarize_ocr_for_knowledge(
    ocr_full_text: str,
    *,
    goods_name: str = "",
    goods_id: str = "",
    sku_hints: Optional[List[str]] = None,
    use_llm: Optional[bool] = None,
    api_commerce_note: str = "",
) -> str:
    """将 OCR 合并文本整理为 Markdown 参数小节，供写入知识库。"""
    text = (ocr_full_text or "").strip()
    if not text:
        return ""

    if use_llm is None:
        use_llm = bool(get_config("knowledge_base.goods_sync_ocr_summarize_with_llm", False))

    lines_flat: List[str] = []
    for part in re.split(r"[\n|]+", text):
        p = part.strip()
        if not p or p.startswith("图片") or p.startswith("【"):
            continue
        if looks_like_commerce_line(p):
            continue
        lines_flat.append(p)
    lines_flat = filter_ocr_lines(lines_flat)

    if not use_llm:
        return _rule_based_summary(lines_flat, goods_name)

    api_key = (get_config("llm.api_key", "") or "").strip()
    if not api_key:
        logger.debug("未配置 llm.api_key，OCR 摘要使用规则提取")
        return _rule_based_summary(lines_flat, goods_name)

    try:
        from openai import OpenAI
    except ImportError:
        return _rule_based_summary(lines_flat, goods_name)

    api_base = (get_config("llm.api_base", "") or "").strip()
    model = (get_config("llm.model_name", "") or "gpt-4o-mini").strip()
    timeout = float(get_config("llm.request_timeout_sec", 35) or 35)
    max_tokens = int(get_config("knowledge_base.goods_sync_ocr_summarize_max_tokens", 800) or 800)

    sku_block = ""
    if sku_hints:
        sku_block = "\n已知规格名称（仅作参考，勿写价格）：\n" + "\n".join(
            f"- {s}" for s in sku_hints[:20]
        )

    anchor = (api_commerce_note or "").strip()
    anchor_block = (
        f"\n【接口已提供的权威价格/库存（禁止在摘要中重复或改写）】\n{anchor}\n"
        if anchor
        else ""
    )

    system = (
        "你是电商商品资料编辑。根据商品详情图 OCR 文字，整理客服知识库用的参数说明。"
        "硬性规则："
        "1) 严禁输出任何价格、拼单价、券后价、原价、库存、销量、SKU 价格；"
        "2) 只写 OCR 中明确出现的非商业参数（功率、尺寸、材质、功能、配件、认证等）；"
        "3) 不得编造；OCR 缺字处不要猜；"
        "4) 输出 Markdown 二级标题「图文参数摘要」，下列表，400 字以内。"
    )
    user = (
        f"商品名：{goods_name or '未知'}\n"
        f"商品 ID：{goods_id or '未知'}\n"
        f"{anchor_block}"
        f"{sku_block}\n\n"
        f"OCR 原文（已尽量剔除价格行）：\n" + "\n".join(lines_flat)[:6000]
    )

    try:
        client = OpenAI(api_key=api_key, base_url=api_base or None)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.1,
            timeout=timeout,
        )
        content = filter_summary_markdown(
            (resp.choices[0].message.content or "").strip()
        )
        if content:
            if not content.lstrip().startswith("#"):
                content = "## 图文参数摘要（OCR 整理，不含价格）\n\n" + content
            return content
    except Exception as e:
        logger.warning(f"OCR LLM 摘要失败，改用规则提取: {e}")

    return _rule_based_summary(lines_flat, goods_name)
