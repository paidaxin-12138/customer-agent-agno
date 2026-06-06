"""聊天图片 LRU 缓存测试。"""
import pytest
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication

from utils.chat_image_cache import MAX_CACHED_IMAGES, ChatImageCache


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


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
