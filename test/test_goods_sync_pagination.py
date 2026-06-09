# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
from scripts.sync_goods_to_kb import _should_fetch_next_goods_page


def test_continue_when_api_returns_10_of_52():
    items = [{"goods_id": i} for i in range(10)]
    assert _should_fetch_next_goods_page(
        product_list=items,
        page_size=50,
        total_api=52,
        catalog_count=10,
    )


def test_stop_when_catalog_reaches_total():
    items = [{"goods_id": i} for i in range(2)]
    assert not _should_fetch_next_goods_page(
        product_list=items,
        page_size=50,
        total_api=52,
        catalog_count=52,
    )


def test_stop_on_empty_page():
    assert not _should_fetch_next_goods_page(
        product_list=[],
        page_size=50,
        total_api=52,
        catalog_count=40,
    )


def test_continue_when_total_unknown_full_page():
    items = [{"goods_id": i} for i in range(10)]
    assert _should_fetch_next_goods_page(
        product_list=items,
        page_size=50,
        total_api=0,
        catalog_count=10,
    )


def test_stop_when_total_unknown_partial_page():
    items = [{"goods_id": i} for i in range(2)]
    assert not _should_fetch_next_goods_page(
        product_list=items,
        page_size=50,
        total_api=0,
        catalog_count=52,
    )


def test_fallback_when_total_unknown():
    short = [{"goods_id": 1}] * 2
    assert not _should_fetch_next_goods_page(
        product_list=short,
        page_size=50,
        total_api=0,
        catalog_count=52,
    )
