#!/usr/bin/env python3
"""
OCR 工具：识别商品主图/详情图文字，并格式化为可写入知识库的 Markdown。
依赖（可选）：uv sync --extra ocr  →  paddlepaddle + paddleocr
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from config import get_config
from utils.logger_loguru import get_logger
from utils.product_image_urls import collect_product_images, dedupe_urls

logger = get_logger("OCR")

_ocr_engine = None
_ocr_engine_det_limit: int = 1920
_cpu_limited = False


def limit_ocr_cpu_usage(max_threads: int = 2) -> None:
    """限制 Paddle/OMP 线程数，避免同步时占满 CPU 导致界面假死。"""
    global _cpu_limited
    if _cpu_limited:
        return
    _cpu_limited = True
    n = str(max(1, int(max_threads)))
    os.environ.setdefault("OMP_NUM_THREADS", n)
    os.environ.setdefault("MKL_NUM_THREADS", n)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", n)
    try:
        import paddle

        paddle.set_num_threads(int(n))
    except Exception:
        pass


@dataclass
class OcrRunConfig:
    enabled: bool = True
    max_main_images: int = 3
    max_detail_images: int = 6
    max_lines_per_image: int = 80
    download_timeout_sec: int = 15
    summarize_with_llm: bool = False
    include_raw_ocr: bool = True
    min_rec_score: float = 0.45
    det_limit_side_len: int = 1920

    @classmethod
    def from_config(cls) -> "OcrRunConfig":
        return cls(
            enabled=bool(get_config("knowledge_base.goods_sync_ocr_enabled", True)),
            max_main_images=int(get_config("knowledge_base.goods_sync_ocr_max_main_images", 3) or 3),
            max_detail_images=int(get_config("knowledge_base.goods_sync_ocr_max_detail_images", 6) or 6),
            max_lines_per_image=int(get_config("knowledge_base.goods_sync_ocr_max_lines_per_image", 80) or 80),
            download_timeout_sec=int(get_config("knowledge_base.goods_sync_ocr_download_timeout_sec", 15) or 15),
            summarize_with_llm=bool(
                get_config("knowledge_base.goods_sync_ocr_summarize_with_llm", False)
            ),
            include_raw_ocr=bool(
                get_config("knowledge_base.goods_sync_ocr_include_raw", True)
            ),
            min_rec_score=float(get_config("knowledge_base.goods_sync_ocr_min_rec_score", 0.45) or 0.45),
            det_limit_side_len=int(
                get_config("knowledge_base.goods_sync_ocr_det_limit_side_len", 1920) or 1920
            ),
        )


def get_ocr_engine(det_limit_side_len: int = 1920):
    """PaddleOCR 单例（首次调用时加载）。"""
    global _ocr_engine, _ocr_engine_det_limit
    det_limit_side_len = int(det_limit_side_len or 1920)
    if _ocr_engine is None or _ocr_engine_det_limit != det_limit_side_len:
        try:
            from paddleocr import PaddleOCR

            limit_ocr_cpu_usage(
                int(get_config("knowledge_base.goods_sync_ocr_cpu_threads", 2) or 2)
            )
            # PaddleOCR 3.x：关闭文档矫正；提高 det 边长利于详情长图
            _ocr_engine = PaddleOCR(
                lang="ch",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=True,
                text_det_limit_side_len=det_limit_side_len,
                text_rec_score_thresh=0.0,
            )
            _ocr_engine_det_limit = det_limit_side_len
            logger.info("PaddleOCR 初始化成功")
        except ImportError:
            logger.error("未安装 PaddleOCR，请执行: uv sync --extra ocr")
            raise
        except Exception as e:
            logger.error(f"PaddleOCR 初始化失败: {e}")
            raise
    return _ocr_engine


def download_image(image_url: str, timeout: int = 10) -> Optional[str]:
    try:
        response = requests.get(image_url, timeout=timeout)
        response.raise_for_status()

        suffix = "jpg"
        clean = image_url.split("?", 1)[0]
        if "." in clean:
            ext = clean.rsplit(".", 1)[-1].lower()
            if ext in ("jpg", "jpeg", "png", "webp", "gif") and len(ext) <= 5:
                suffix = ext

        fd, temp_path = tempfile.mkstemp(suffix=f".{suffix}")
        with os.fdopen(fd, "wb") as f:
            f.write(response.content)
        return temp_path
    except Exception as e:
        logger.debug(f"下载图片失败 {image_url[:80]}: {e}")
        return None


def _box_sort_key(box: Any) -> tuple:
    try:
        if hasattr(box, "tolist"):
            box = box.tolist()
        if isinstance(box, (list, tuple)) and len(box) >= 4:
            if isinstance(box[0], (list, tuple)):
                ys = [p[1] for p in box]
                xs = [p[0] for p in box]
            else:
                ys = [box[1], box[3]]
                xs = [box[0], box[2]]
            return (min(ys), min(xs))
    except Exception:
        pass
    return (0, 0)


def _texts_from_ocr_result_item(
    item: Any,
    *,
    min_rec_score: float = 0.45,
) -> List[str]:
    """PaddleOCR 3.x：按阅读顺序输出，过滤低置信度与价格行。"""
    from utils.ocr_content_filter import filter_ocr_lines, looks_like_commerce_line

    if item is None:
        return []

    rec_texts: List[str] = []
    rec_scores: List[float] = []
    rec_boxes: List[Any] = []

    if isinstance(item, dict):
        rec_texts = list(item.get("rec_texts") or [])
        rec_scores = list(item.get("rec_scores") or [])
        rec_boxes = list(item.get("rec_boxes") or item.get("rec_polys") or [])
    elif hasattr(item, "get"):
        rec_texts = list(item.get("rec_texts") or item.get("rec_text") or [])
        rec_scores = list(item.get("rec_scores") or [])
        rec_boxes = list(item.get("rec_boxes") or item.get("rec_polys") or [])
    elif hasattr(item, "rec_texts"):
        rec_texts = list(getattr(item, "rec_texts", None) or [])
        rec_scores = list(getattr(item, "rec_scores", None) or [])
        rec_boxes = list(getattr(item, "rec_boxes", None) or getattr(item, "rec_polys", None) or [])

    if rec_texts:
        ranked: List[tuple] = []
        for i, raw in enumerate(rec_texts):
            t = str(raw).strip()
            if not t:
                continue
            score = float(rec_scores[i]) if i < len(rec_scores) else 1.0
            if score < min_rec_score:
                continue
            if looks_like_commerce_line(t):
                continue
            box = rec_boxes[i] if i < len(rec_boxes) else None
            ranked.append((*_box_sort_key(box), t))
        ranked.sort(key=lambda x: (x[0], x[1]))
        return filter_ocr_lines([x[2] for x in ranked])

    if isinstance(item, list):
        texts: List[str] = []
        for line in item:
            if not line:
                continue
            if isinstance(line, (list, tuple)) and len(line) >= 2:
                part = line[1]
                if isinstance(part, (list, tuple)) and part:
                    texts.append(str(part[0]).strip())
                elif isinstance(part, str):
                    texts.append(part.strip())
        return filter_ocr_lines(texts)
    return []


def _run_ocr_on_file(
    image_path: str,
    *,
    det_limit_side_len: int = 1920,
    min_rec_score: float = 0.45,
) -> List[str]:
    engine = get_ocr_engine(det_limit_side_len)
    result = engine.predict(image_path)
    texts: List[str] = []
    if not result:
        return texts
    if isinstance(result, list):
        for item in result:
            texts.extend(
                _texts_from_ocr_result_item(item, min_rec_score=min_rec_score)
            )
    else:
        texts.extend(
            _texts_from_ocr_result_item(result, min_rec_score=min_rec_score)
        )
    return texts


def extract_text_from_image(
    image_path: str,
    max_lines: int = 80,
    *,
    det_limit_side_len: int = 1920,
    min_rec_score: float = 0.45,
) -> List[str]:
    from utils.ocr_image_preprocess import prepare_ocr_image_paths

    slice_paths: List[str] = []
    try:
        slice_paths = prepare_ocr_image_paths(image_path)
        merged: List[str] = []
        seen: set[str] = set()
        for sp in slice_paths:
            for t in _run_ocr_on_file(
                sp,
                det_limit_side_len=det_limit_side_len,
                min_rec_score=min_rec_score,
            ):
                if t not in seen:
                    seen.add(t)
                    merged.append(t)
                if len(merged) >= max_lines:
                    return merged[:max_lines]
        return merged[:max_lines]
    except Exception as e:
        logger.debug(f"OCR 识别失败 {image_path}: {e}")
        return []
    finally:
        for sp in slice_paths:
            if sp != image_path:
                try:
                    os.remove(sp)
                except OSError:
                    pass


def extract_text_from_urls(
    image_urls: List[str],
    *,
    label_prefix: str = "图",
    max_images: int = 5,
    max_lines_per_image: int = 80,
    timeout: int = 15,
    det_limit_side_len: int = 1920,
    min_rec_score: float = 0.45,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "success": False,
        "sections": [],
        "all_lines": [],
        "full_text": "",
        "count": 0,
    }
    if not image_urls:
        return result

    sections: List[Dict[str, Any]] = []
    all_lines: List[str] = []

    for i, url in enumerate(image_urls[:max_images]):
        temp_path = None
        try:
            temp_path = download_image(url, timeout=timeout)
            if not temp_path:
                continue
            texts = extract_text_from_image(
                temp_path,
                max_lines=max_lines_per_image,
                det_limit_side_len=det_limit_side_len,
                min_rec_score=min_rec_score,
            )
            if texts:
                sections.append(
                    {
                        "index": i,
                        "label": f"{label_prefix}{i + 1}",
                        "url": url,
                        "texts": texts,
                        "full": "\n".join(texts),
                    }
                )
                all_lines.extend(texts)
        except Exception as e:
            logger.debug(f"OCR 跳过 {url[:60]}: {e}")
        finally:
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    if sections:
        result["success"] = True
        result["sections"] = sections
        result["all_lines"] = all_lines
        result["count"] = len(sections)
        result["full_text"] = "\n".join(
            f"【{s['label']}】{s['full']}" for s in sections
        )
    return result


def build_product_ocr_knowledge_section(
    detail: Dict[str, Any],
    product: Dict[str, Any],
    *,
    raw_api_result: Optional[Dict[str, Any]] = None,
    cfg: Optional[OcrRunConfig] = None,
    goods_name: str = "",
    goods_id: str = "",
    sku_hints: Optional[List[str]] = None,
    api_commerce_note: str = "",
) -> str:
    """
    对商品主图 + 详情图 OCR，并生成写入知识库的 Markdown 块。
    未启用 OCR、无图或识别失败时返回空字符串。
    """
    cfg = cfg or OcrRunConfig.from_config()
    if not cfg.enabled:
        return ""

    groups = collect_product_images(detail, product, raw_api_result=raw_api_result)
    main_urls = dedupe_urls(groups.get("main_images") or [], limit=cfg.max_main_images)
    detail_urls = dedupe_urls(groups.get("detail_images") or [], limit=cfg.max_detail_images)

    if not main_urls and not detail_urls:
        return ""

    try:
        ocr_kw = dict(
            max_lines_per_image=cfg.max_lines_per_image,
            timeout=cfg.download_timeout_sec,
            det_limit_side_len=cfg.det_limit_side_len,
            min_rec_score=cfg.min_rec_score,
        )
        main_ocr = extract_text_from_urls(
            main_urls,
            label_prefix="主图",
            max_images=cfg.max_main_images,
            **ocr_kw,
        )
        detail_ocr = extract_text_from_urls(
            detail_urls,
            label_prefix="详情图",
            max_images=cfg.max_detail_images,
            **ocr_kw,
        )
    except ImportError:
        return (
            "\n\n> OCR 未安装：请在项目目录执行 `uv sync --extra ocr` 后重新同步商品。\n"
        )

    if not main_ocr.get("success") and not detail_ocr.get("success"):
        return ""

    from utils.ocr_content_filter import filter_ocr_text_block

    blocks: List[str] = [
        "",
        "## 图文参数补充（OCR，仅供参考）",
        "",
        "> **报价与库存一律以文档前部「在售价格与库存（接口数据）」为准；"
        "本节已剔除 OCR 中的价格字样，不得用于回答买家价格。**",
        "",
    ]
    if api_commerce_note.strip():
        blocks.append(api_commerce_note.strip())
        blocks.append("")

    if cfg.include_raw_ocr:
        if main_ocr.get("success"):
            raw_main = filter_ocr_text_block(main_ocr["full_text"])
            if raw_main:
                blocks.append(f"### 主图 OCR（{main_ocr['count']} 张）")
                blocks.append("")
                blocks.append(raw_main)
                blocks.append("")
        if detail_ocr.get("success"):
            raw_detail = filter_ocr_text_block(detail_ocr["full_text"])
            if raw_detail:
                blocks.append(f"### 详情图 OCR（{detail_ocr['count']} 张）")
                blocks.append("")
                blocks.append(raw_detail)
                blocks.append("")

    combined = filter_ocr_text_block(
        "\n".join(
            x
            for x in (main_ocr.get("full_text", ""), detail_ocr.get("full_text", ""))
            if x
        )
    )
    if combined.strip() and cfg.summarize_with_llm:
        from scripts.ocr_summarize import summarize_ocr_for_knowledge

        summary = summarize_ocr_for_knowledge(
            combined,
            goods_name=goods_name,
            goods_id=goods_id,
            sku_hints=sku_hints,
            use_llm=True,
            api_commerce_note=api_commerce_note,
        )
        if summary.strip():
            blocks.extend(["", summary.strip(), ""])
    elif combined.strip() and not cfg.summarize_with_llm:
        from scripts.ocr_summarize import summarize_ocr_for_knowledge

        summary = summarize_ocr_for_knowledge(
            combined,
            goods_name=goods_name,
            goods_id=goods_id,
            sku_hints=sku_hints,
            use_llm=False,
        )
        if summary.strip():
            blocks.extend(["", summary.strip(), ""])

    blocks.append("---")
    blocks.append("*OCR 可能有缺字，且不含价格；报价请用接口数据或 get_shop_products 工具。*")
    return "\n".join(blocks)


def ocr_product_images(image_urls: List[str]) -> str:
    """兼容旧接口：识别 URL 列表并返回 Markdown。"""
    ocr_result = extract_text_from_urls(image_urls)
    if not ocr_result.get("success"):
        return "暂无图片文字信息"
    return "\n".join(
        [
            "## 图片文字信息（OCR 识别）",
            "",
            f"共识别 {ocr_result['count']} 张图片",
            "",
            ocr_result["full_text"],
            "",
        ]
    )
