# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""聊天图片 LRU 缓存测试。"""
import pytest
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication

from utils.chat_image_cache import MAX_CACHED_IMAGES, ChatImageCache


def test_retain_only_evicts_off_viewport_urls(qapp):
    cache = ChatImageCache()
    cache.clear()

    for i in range(MAX_CACHED_IMAGES + 5):
        pm = QPixmap(10, 10)
        pm.fill()
        cache._put_locked(f"http://example.com/{i}.png", pm)

    assert len(cache._cache) == MAX_CACHED_IMAGES
    cache.retain_only({f"http://example.com/{MAX_CACHED_IMAGES + 4}.png"})
    assert len(cache._cache) == 1
