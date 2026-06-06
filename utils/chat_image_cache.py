"""聊天图片 LRU 缓存（最多 20 张），滚动出视口后释放内存。"""
from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict
from typing import Callable, Optional, Set

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QPixmapCache

from utils.logger_loguru import get_logger

_log = get_logger("ChatImageCache")

MAX_CACHED_IMAGES = 20
_QPIXMAP_CACHE_KB = 20480  # ~20MB

_IMAGE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Referer": "https://mms.pinduoduo.com/",
}


class _ImageFetchThread(QThread):
    loaded = pyqtSignal(str, QPixmap)
    failed = pyqtSignal(str)

    def __init__(self, url: str):
        super().__init__()
        self._url = (url or "").strip()

    def run(self) -> None:
        url = self._url
        if not url:
            self.failed.emit(url)
            return
        try:
            from utils.url_fetch_guard import is_url_safe_to_fetch

            ok, _reason = is_url_safe_to_fetch(url, purpose="chat_image")
            if not ok:
                self.failed.emit(url)
                return

            import aiohttp

            async def fetch_image() -> bytes:
                timeout = aiohttp.ClientTimeout(total=12)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url, headers=_IMAGE_HEADERS) as response:
                        if response.status >= 400:
                            raise ValueError(f"HTTP {response.status}")
                        return await response.read()

            image_data = asyncio.run(fetch_image())
            if not image_data:
                raise ValueError("empty body")
            pixmap = QPixmap()
            if not pixmap.loadFromData(image_data) or pixmap.isNull():
                raise ValueError("not a decodable image")
            self.loaded.emit(url, pixmap)
        except Exception as exc:
            _log.debug("聊天图片加载失败 url={}: {}", url[:80], exc)
            self.failed.emit(url)


class ChatImageCache(QObject):
    """全局聊天图片缓存；主线程访问，后台线程拉取。"""

    pixmap_loaded = pyqtSignal(str)
    pixmap_failed = pyqtSignal(str)

    _instance: Optional["ChatImageCache"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        super().__init__()
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._loading: Set[str] = set()
        self._failed: Set[str] = set()
        self._threads: dict[str, _ImageFetchThread] = {}
        self._lock = threading.Lock()
        QPixmapCache.setCacheLimit(_QPIXMAP_CACHE_KB)

    @classmethod
    def instance(cls) -> "ChatImageCache":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def get(self, url: str) -> Optional[QPixmap]:
        key = (url or "").strip()
        if not key:
            return None
        with self._lock:
            pm = self._cache.get(key)
            if pm is not None:
                self._cache.move_to_end(key)
            return pm

    def is_failed(self, url: str) -> bool:
        return (url or "").strip() in self._failed

    def request(self, url: str, on_loaded: Optional[Callable[[str], None]] = None) -> None:
        key = (url or "").strip()
        if not key:
            return
        with self._lock:
            if key in self._cache or key in self._loading or key in self._failed:
                return
            self._loading.add(key)
        thread = _ImageFetchThread(key)
        self._threads[key] = thread

        def _done(u: str, pm: QPixmap) -> None:
            with self._lock:
                self._loading.discard(u)
                self._threads.pop(u, None)
                self._put_locked(u, pm)
            if on_loaded:
                on_loaded(u)
            self.pixmap_loaded.emit(u)

        def _fail(u: str) -> None:
            with self._lock:
                self._loading.discard(u)
                self._failed.add(u)
                self._threads.pop(u, None)
            self.pixmap_failed.emit(u)

        thread.loaded.connect(_done)
        thread.failed.connect(_fail)
        thread.start()

    def retain_only(self, urls: Set[str]) -> None:
        """释放不在 urls 集合中的图片，供滚动出视口后回收内存。"""
        keep = {(u or "").strip() for u in urls if (u or "").strip()}
        with self._lock:
            for key in list(self._cache.keys()):
                if key not in keep:
                    self._cache.pop(key, None)
                    QPixmapCache.remove(key)

    def _put_locked(self, url: str, pixmap: QPixmap) -> None:
        self._cache[url] = pixmap
        self._cache.move_to_end(url)
        QPixmapCache.insert(url, pixmap)
        while len(self._cache) > MAX_CACHED_IMAGES:
            old_key, _old_pm = self._cache.popitem(last=False)
            QPixmapCache.remove(old_key)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._loading.clear()
            self._failed.clear()
            for t in list(self._threads.values()):
                if t.isRunning():
                    t.quit()
                    t.wait(200)
            self._threads.clear()


def get_chat_image_cache() -> ChatImageCache:
    return ChatImageCache.instance()
