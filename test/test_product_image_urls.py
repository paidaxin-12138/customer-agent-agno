"""商品图 URL 提取"""

from utils.product_image_urls import (
    collect_product_images,
    dedupe_urls,
    extract_urls_from_html,
    normalize_image_url,
)


def test_normalize_protocol_relative():
    assert normalize_image_url("//img.pddpic.com/a.jpg").startswith("https://")


def test_extract_urls_from_html():
    html = '<p>说明</p><img src="//img.pddpic.com/goods/1.jpg" />'
    urls = extract_urls_from_html(html)
    assert len(urls) >= 1
    assert urls[0].startswith("https://")


def test_collect_main_and_detail():
    detail = {
        "thumb_url": "https://img.pddpic.com/main.jpg",
        "description": '<img src="https://img.pddpic.com/detail1.png">',
    }
    groups = collect_product_images(detail)
    assert groups["main_images"]
    assert groups["detail_images"]
    assert groups["all_images"]


def test_dedupe_preserves_order():
    urls = dedupe_urls(
        [
            "https://a.com/1.jpg",
            "https://a.com/1.jpg",
            "https://a.com/2.jpg",
        ],
        limit=2,
    )
    assert urls == [
        "https://a.com/1.jpg",
        "https://a.com/2.jpg",
    ]
