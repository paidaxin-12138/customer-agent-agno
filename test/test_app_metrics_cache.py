# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""app_metrics 缓存规模指标。"""
from core.app_metrics import get_cache_sizes, get_metrics_payload


def test_get_cache_sizes_keys():
    sizes = get_cache_sizes()
    assert "hub_accounts" in sizes
    assert "hub_buyers_total" in sizes
    assert "image_cache_count" in sizes
    assert "buyer_lock_registry" in sizes


def test_metrics_payload_includes_cache_sizes():
    payload = get_metrics_payload()
    assert "cache_sizes" in payload
    assert isinstance(payload["cache_sizes"], dict)
