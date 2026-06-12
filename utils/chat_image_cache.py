# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
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
_THREAD_DRAIN_MS = 8000

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

    def __init__(self, url: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._url = (url or "").strip()

    def run(self) -> None:
        url = self._url
        if not url:
            self.failed.emit(url)
            return
        try:
            from utils.url_fetch_guard import aiohttp_fetch_bytes

            image_data = asyncio.run(
                aiohttp_fetch_bytes(
                    url,
                    purpose="chat_image",
                    headers=_IMAGE_HEADERS,
                )
            )
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
            existing = self._threads.get(key)
            if existing is not None and existing.isRunning():
                return
            self._loading.add(key)

        thread = _ImageFetchThread(key, self)

        def _done(u: str, pm: QPixmap) -> None:
            with self._lock:
                self._loading.discard(u)
                self._put_locked(u, pm)
            if on_loaded:
                on_loaded(u)
            self.pixmap_loaded.emit(u)

        def _fail(u: str) -> None:
            with self._lock:
                self._loading.discard(u)
                self._failed.add(u)
            self.pixmap_failed.emit(u)

        def _thread_finished(u: str = key) -> None:
            with self._lock:
                self._threads.pop(u, None)

        thread.loaded.connect(_done)
        thread.failed.connect(_fail)
        thread.finished.connect(_thread_finished)
        thread.finished.connect(thread.deleteLater)

        with self._lock:
            self._threads[key] = thread
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

    def drain_running_threads(self, wait_ms: int = _THREAD_DRAIN_MS) -> None:
        """等待进行中的拉取线程结束，避免 QThread 在 run() 期间被销毁。"""
        with self._lock:
            threads = list(self._threads.values())
        for thread in threads:
            if thread.isRunning():
                thread.wait(max(0, int(wait_ms)))

    def clear(self) -> None:
        self.drain_running_threads()
        with self._lock:
            self._cache.clear()
            self._loading.clear()
            self._failed.clear()
            self._threads.clear()


def get_chat_image_cache() -> ChatImageCache:
    return ChatImageCache.instance()
