"""远程店铺 Logo 加载（QThread）。拼多多 CDN 常要求浏览器类请求头，否则返回非图片正文。"""

from __future__ import annotations

import asyncio

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPainter, QPainterPath, QPixmap

from utils.logger_loguru import get_logger

logger = get_logger(__name__)

_LOGO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Referer": "https://mms.pinduoduo.com/",
}


class LogoLoaderThread(QThread):
    """异步加载 Logo；失败时发射空 QPixmap。"""

    logo_loaded = pyqtSignal(QPixmap)

    def __init__(self, url: str):
        super().__init__()
        self.url = url or ""

    def run(self):
        if not (self.url or "").strip():
            self.logo_loaded.emit(QPixmap())
            return
        try:
            import aiohttp

            async def fetch_image():
                timeout = aiohttp.ClientTimeout(total=12)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(self.url, headers=_LOGO_HEADERS) as response:
                        if response.status >= 400:
                            raise ValueError(f"HTTP {response.status}")
                        return await response.read()

            image_data = asyncio.run(fetch_image())
            if not image_data:
                raise ValueError("empty body")

            snippet = image_data[:120]
            if snippet.lstrip().startswith(b"<"):
                logger.debug(
                    "店铺 Logo URL 返回疑似 HTML 而非图片: url={} snippet={!r}",
                    self.url,
                    snippet[:80],
                )

            pixmap = QPixmap()
            pixmap.loadFromData(image_data)
            if pixmap.isNull():
                raise ValueError("response is not a decodable image")

            size = 60
            circular_pixmap = QPixmap(size, size)
            circular_pixmap.fill(Qt.GlobalColor.transparent)

            painter = QPainter(circular_pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            path = QPainterPath()
            path.addEllipse(0, 0, size, size)
            painter.setClipPath(path)

            scaled_pixmap = pixmap.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(0, 0, scaled_pixmap)
            painter.end()

            self.logo_loaded.emit(circular_pixmap)
        except Exception as e:
            logger.warning("店铺 Logo 加载失败: url={} err={}", self.url, e)
            self.logo_loaded.emit(QPixmap())
