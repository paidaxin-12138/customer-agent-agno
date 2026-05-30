"""
从拼多多商品详情 API 结果中收集主图、轮播图、详情页图中的 URL。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin

_IMG_URL_RE = re.compile(
    r"https?://[^\s\"'<>]+\.(?:jpg|jpeg|png|webp|gif)(?:\?[^\s\"'<>]*)?",
    re.IGNORECASE,
)
_HTML_IMG_SRC_RE = re.compile(
    r"""<img[^>]+src\s*=\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)
_CSS_URL_RE = re.compile(
    r"""url\(\s*['"]?([^'")\s]+)['"]?\s*\)""",
    re.IGNORECASE,
)

_URL_FIELD_NAMES = frozenset(
    {
        "url",
        "img_url",
        "imgUrl",
        "image_url",
        "imageUrl",
        "pic_url",
        "picUrl",
        "thumb_url",
        "thumbUrl",
        "hd_thumb_url",
        "hdThumbUrl",
        "original",
        "src",
    }
)

_MAIN_GALLERY_KEYS = frozenset(
    {
        "carousel_gallery",
        "carouselGallery",
        "gallery",
        "gallery_list",
        "galleryList",
        "image_url_list",
        "imageUrlList",
        "goods_gallery",
        "goodsGallery",
        "top_gallery",
        "topGallery",
        "view_image_list",
        "viewImageList",
        "skc_gallery",
        "skcGallery",
    }
)

_DETAIL_GALLERY_KEYS = frozenset(
    {
        "detail_gallery",
        "detailGallery",
        "detail_list",
        "detailList",
        "goods_detail_images",
        "goodsDetailImages",
        "decoration",
        "decoration_list",
        "decorationList",
    }
)


def normalize_image_url(url: str, base: str = "https:") -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return urljoin("https://img.pddpic.com", u)
    return u


def looks_like_image_url(url: str) -> bool:
    u = normalize_image_url(url)
    if not u.startswith(("http://", "https://")):
        return False
    lower = u.lower().split("?", 1)[0]
    if any(lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return True
    return any(
        token in lower
        for token in ("pddpic", "yangkeduo", "img-", "/image", "gallery", "jpeg")
    )


def extract_urls_from_html(html: str) -> List[str]:
    if not html or not isinstance(html, str):
        return []
    found: List[str] = []
    for pattern in (_HTML_IMG_SRC_RE, _CSS_URL_RE):
        for m in pattern.finditer(html):
            u = normalize_image_url(m.group(1))
            if looks_like_image_url(u):
                found.append(u)
    for m in _IMG_URL_RE.finditer(html):
        u = normalize_image_url(m.group(0))
        if looks_like_image_url(u):
            found.append(u)
    return found


def _urls_from_node(node: Any, depth: int = 0) -> List[str]:
    if depth > 8 or node is None:
        return []
    if isinstance(node, str):
        u = normalize_image_url(node)
        return [u] if looks_like_image_url(u) else []
    if isinstance(node, list):
        out: List[str] = []
        for item in node:
            out.extend(_urls_from_node(item, depth + 1))
        return out
    if isinstance(node, dict):
        out: List[str] = []
        for key in _URL_FIELD_NAMES:
            if key in node:
                out.extend(_urls_from_node(node.get(key), depth + 1))
        for key, val in node.items():
            if key in _URL_FIELD_NAMES:
                continue
            if isinstance(val, (dict, list)):
                out.extend(_urls_from_node(val, depth + 1))
        return out
    return []


def _pick_by_keys(data: dict, keys: frozenset) -> List[str]:
    urls: List[str] = []
    for key in keys:
        if key in data:
            urls.extend(_urls_from_node(data.get(key)))
    return urls


def dedupe_urls(urls: List[str], limit: Optional[int] = None) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for raw in urls:
        u = normalize_image_url(raw)
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
        if limit is not None and len(out) >= limit:
            break
    return out


def collect_product_images(
    detail: Optional[Dict[str, Any]] = None,
    product: Optional[Dict[str, Any]] = None,
    raw_api_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[str]]:
    """
    汇总主图与详情图 URL。

    Returns:
        main_images, detail_images, all_images
    """
    detail = detail or {}
    product = product or {}
    raw = raw_api_result if isinstance(raw_api_result, dict) else {}

    main: List[str] = []
    detail_imgs: List[str] = []

    for src in (
        detail.get("thumb_url"),
        detail.get("hd_thumb_url"),
        product.get("thumb_url"),
    ):
        if src:
            main.append(normalize_image_url(str(src)))

    main.extend(_pick_by_keys(raw, _MAIN_GALLERY_KEYS))
    main.extend(_pick_by_keys(detail, _MAIN_GALLERY_KEYS))

    detail_imgs.extend(_pick_by_keys(raw, _DETAIL_GALLERY_KEYS))
    detail_imgs.extend(_pick_by_keys(detail, _DETAIL_GALLERY_KEYS))

    desc = detail.get("description") or product.get("description") or ""
    if isinstance(desc, str) and desc.strip():
        detail_imgs.extend(extract_urls_from_html(desc))

    brief = detail.get("brief") or ""
    if isinstance(brief, str) and "<img" in brief.lower():
        detail_imgs.extend(extract_urls_from_html(brief))

    legacy = detail.get("image_urls") or product.get("image_urls") or []
    if isinstance(legacy, list):
        main.extend(normalize_image_url(str(u)) for u in legacy if u)

    main = dedupe_urls(main)
    detail_imgs = dedupe_urls([u for u in detail_imgs if u not in set(main)])
    all_urls = dedupe_urls(main + detail_imgs)

    return {
        "main_images": main,
        "detail_images": detail_imgs,
        "all_images": all_urls,
    }
