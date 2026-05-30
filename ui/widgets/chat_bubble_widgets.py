"""实时聊天消息气泡（QListWidget + 自定义 QWidget，QPainter 三角箭头）。"""
from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime
from typing import Any, Literal, Optional, Tuple

from PyQt6.QtCore import Qt, QSize, QPoint, QThread, pyqtSignal, QTimer, QRect
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSizePolicy,
    QStackedLayout,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from utils.chat_message_html import format_chat_bubble_html
from ui import apple_ui_tokens as UI

# 与主窗口背景一致（apple_ui_tokens.BG_PRIMARY）
CHAT_BG = UI.BG_PRIMARY
SELF_BUBBLE = "#0A84FF"
SELF_TEXT = "#FFFFFF"
OTHER_BUBBLE = "#2C2C3A"
OTHER_TEXT = "#E5E5E5"
OTHER_BORDER = "#3A3A4A"
TIME_TEXT = "#8E8E93"
SYSTEM_BG = "#2C2C3A"
SYSTEM_TEXT = "#98989D"

_URL_RE = re.compile(r"https?://", re.I)
_BUBBLE_MAX_W = 420
_IMG_MAX_W = 280
_IMG_MAX_H = 320
_IMG_PLACEHOLDER_H = 120
# 多行 QLabel 高度估算余量（fontMetrics / 圆角边框）
_BUBBLE_HEIGHT_SLACK = 10
_ITEM_HEIGHT_SLACK = 6

_IMAGE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Referer": "https://mms.pinduoduo.com/",
}


class _BubbleArrow(QWidget):
    """QPainter 绘制三角箭头（Qt QSS 不支持 ::before/::after）。"""

    def __init__(self, *, pointing: Literal["left", "right"], color: str, parent=None):
        super().__init__(parent)
        self._pointing = pointing
        self._color = QColor(color)
        self.setFixedSize(10, 14)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(Qt.PenStyle.NoPen))
        p.setBrush(QBrush(self._color))
        if self._pointing == "left":
            pts = [QPoint(9, 7), QPoint(0, 1), QPoint(0, 13)]
        else:
            pts = [QPoint(0, 7), QPoint(9, 1), QPoint(9, 13)]
        p.drawPolygon(pts)
        p.end()


def _format_timestamp(t: Any) -> str:
    if t is None:
        return ""
    if isinstance(t, datetime):
        return t.strftime("%H:%M")
    return str(t)[:8]


def _needs_rich_html(
    content: str,
    *,
    content_type: Optional[str] = None,
    image_url: Optional[str] = None,
) -> bool:
    ct = (content_type or "text").strip().lower()
    if ct == "image" and (image_url or "").strip():
        return False
    if ct == "video" and (image_url or "").strip():
        return True
    text = (content or "").strip()
    if not text:
        return False
    return bool(_URL_RE.search(text)) or "\n\n" in text


def _build_body(
    content: str,
    *,
    content_type: Optional[str] = None,
    image_url: Optional[str] = None,
    text_color: str,
) -> Tuple[Qt.TextFormat, str]:
    ct = (content_type or "text").strip().lower()
    url = (image_url or "").strip()
    raw = content or ""

    if ct == "video" and url:
        cap = html.escape((raw or "[视频]").strip())
        link_part = format_chat_bubble_html(url) or html.escape(url)
        body = f'<div style="margin-bottom:4px;">{cap}</div>{link_part}'
        return Qt.TextFormat.RichText, _colorize_html(body, text_color)

    if _needs_rich_html(raw, content_type=content_type, image_url=image_url):
        body = format_chat_bubble_html(raw)
        if body:
            return Qt.TextFormat.RichText, _colorize_html(body, text_color)

    return Qt.TextFormat.PlainText, raw


def _colorize_html(body: str, color: str) -> str:
    """RichText 内联颜色，避免 QSS color 被 HTML 默认黑色覆盖。"""
    return (
        f'<div style="color:{color}; background:transparent; margin:0; padding:0;">'
        f"{body}</div>"
    )


def _schedule_list_reflow(widget: QWidget) -> None:
    """图片加载完成后重排所在消息列表。"""
    bubble: QWidget | None = widget
    while bubble is not None and not isinstance(bubble, ChatMessageBubbleWidget):
        bubble = bubble.parentWidget()
    if bubble is None:
        return
    lst: QWidget | None = bubble.parentWidget()
    while lst is not None:
        if lst.objectName() == "LiveChatMsgList":
            layout = lst.layout()
            if isinstance(layout, QVBoxLayout):
                QTimer.singleShot(0, lambda w=lst, ly=layout: reflow_message_widgets(w, ly))
            return
        if isinstance(lst, QListWidget):
            QTimer.singleShot(0, lambda: reflow_message_list_items(lst))
            return
        lst = lst.parentWidget()


class _ChatImageLoaderThread(QThread):
    """后台拉取聊天图片并解码为 QPixmap。"""

    loaded = pyqtSignal(QPixmap)
    failed = pyqtSignal()

    def __init__(self, url: str):
        super().__init__()
        self._url = (url or "").strip()

    def run(self) -> None:
        if not self._url:
            self.failed.emit()
            return
        try:
            import aiohttp

            async def fetch_image() -> bytes:
                timeout = aiohttp.ClientTimeout(total=12)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(self._url, headers=_IMAGE_HEADERS) as response:
                        if response.status >= 400:
                            raise ValueError(f"HTTP {response.status}")
                        return await response.read()

            image_data = asyncio.run(fetch_image())
            if not image_data:
                raise ValueError("empty body")
            pixmap = QPixmap()
            if not pixmap.loadFromData(image_data) or pixmap.isNull():
                raise ValueError("not a decodable image")
            self.loaded.emit(pixmap)
        except Exception:
            self.failed.emit()


class _ImageBubbleBody(QWidget):
    """图片消息：占位符 + QPixmap 异步加载。"""

    size_changed = pyqtSignal()

    def __init__(self, url: str, text_color: str, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatBubbleBodyImage")
        self._loaded_h = _IMG_PLACEHOLDER_H
        self._source_pixmap: QPixmap | None = None
        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)

        self._placeholder = QLabel("加载中…")
        self._placeholder.setObjectName("ChatBubbleImagePlaceholder")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setMinimumSize(160, _IMG_PLACEHOLDER_H)
        self._placeholder.setStyleSheet(
            f"""
            QLabel#ChatBubbleImagePlaceholder {{
                color: {text_color};
                background-color: rgba(255, 255, 255, 0.08);
                border-radius: 10px;
                font-size: 13px;
            }}
            """
        )
        self._stack.addWidget(self._placeholder)

        self._image_label = QLabel()
        self._image_label.setObjectName("ChatBubbleImageLabel")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet("background: transparent; border: none;")
        self._stack.addWidget(self._image_label)

        self._loader = _ChatImageLoaderThread(url)
        self._loader.loaded.connect(self._on_loaded)
        self._loader.failed.connect(self._on_failed)
        self._loader.start()

    def _scale_pixmap(self, pixmap: QPixmap, max_w: int) -> QPixmap:
        w = min(max_w, _IMG_MAX_W)
        return pixmap.scaled(
            w,
            _IMG_MAX_H,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _on_loaded(self, pixmap: QPixmap) -> None:
        self._source_pixmap = pixmap
        scaled = self._scale_pixmap(pixmap, _IMG_MAX_W)
        self._loaded_h = max(_IMG_PLACEHOLDER_H, scaled.height())
        self._image_label.setPixmap(scaled)
        self._image_label.setFixedSize(scaled.size())
        self._stack.setCurrentWidget(self._image_label)
        self.size_changed.emit()
        _schedule_list_reflow(self)

    def _on_failed(self) -> None:
        self._source_pixmap = None
        self._placeholder.setText("图片加载失败")
        self._loaded_h = _IMG_PLACEHOLDER_H
        self.size_changed.emit()
        _schedule_list_reflow(self)

    def content_height_for_width(self, _bubble_width: int) -> int:
        return self._loaded_h

    def reflow_width(self, bubble_width: int) -> None:
        if self._source_pixmap is None or self._source_pixmap.isNull():
            self._placeholder.setMinimumWidth(min(max(80, bubble_width - 24), _IMG_MAX_W))
            return
        inner_w = min(max(80, bubble_width - 24), _IMG_MAX_W)
        scaled = self._scale_pixmap(self._source_pixmap, inner_w)
        self._image_label.setPixmap(scaled)
        self._image_label.setFixedSize(scaled.size())
        self._loaded_h = max(_IMG_PLACEHOLDER_H, scaled.height())


def _avatar_label(letter: str, bg: str) -> QLabel:
    av = QLabel(letter)
    av.setObjectName("ChatBubbleAvatar")
    av.setAlignment(Qt.AlignmentFlag.AlignCenter)
    av.setFixedSize(36, 36)
    av.setStyleSheet(
        f"""
        QLabel#ChatBubbleAvatar {{
            background-color: {bg};
            color: #FFFFFF;
            font-weight: 600;
            font-size: 14px;
            border-radius: 18px;
        }}
        """
    )
    return av


class _BubbleFrame(QFrame):
    """圆角气泡容器；图片用 QPixmap，富文本用 QTextBrowser，纯文本用 QLabel。"""

    def __init__(
        self,
        *,
        side: Literal["left", "right", "system"],
        text_format: Qt.TextFormat,
        text: str,
        text_color: str,
        image_url: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._text_format = text_format
        self._text_color = text_color
        self._image_url = (image_url or "").strip()
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.setMaximumWidth(_BUBBLE_MAX_W)

        if side == "left":
            self.setObjectName("ChatLeftBubbleFrame")
            self.setStyleSheet(
                f"""
                QFrame#ChatLeftBubbleFrame {{
                    background-color: {OTHER_BUBBLE};
                    border: 1px solid {OTHER_BORDER};
                    border-radius: 18px;
                }}
                """
            )
        elif side == "right":
            self.setObjectName("ChatRightBubbleFrame")
            self.setStyleSheet(
                f"""
                QFrame#ChatRightBubbleFrame {{
                    background-color: {SELF_BUBBLE};
                    border: none;
                    border-radius: 18px;
                }}
                """
            )
        else:
            self.setObjectName("ChatSystemBubbleFrame")
            self.setStyleSheet(
                f"""
                QFrame#ChatSystemBubbleFrame {{
                    background-color: {SYSTEM_BG};
                    border-radius: 14px;
                }}
                """
            )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(0)

        self._body = self._create_body_widget(text_format, text, text_color)
        lay.addWidget(self._body)

    def _create_body_widget(
        self, text_format: Qt.TextFormat, text: str, text_color: str
    ) -> QWidget:
        if self._image_url:
            return _ImageBubbleBody(self._image_url, text_color)

        if text_format == Qt.TextFormat.RichText:
            browser = QTextBrowser()
            browser.setObjectName("ChatBubbleBodyBrowser")
            browser.setReadOnly(True)
            browser.setOpenExternalLinks(True)
            browser.setFrameShape(QFrame.Shape.NoFrame)
            browser.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
            browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            browser.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            browser.document().setDocumentMargin(0)
            browser.setStyleSheet(
                f"""
                QTextBrowser#ChatBubbleBodyBrowser {{
                    color: {text_color};
                    background: transparent;
                    border: none;
                    font-size: 15px;
                    padding: 0;
                    margin: 0;
                }}
                """
            )
            browser.setHtml(text)
            return browser

        label = QLabel()
        label.setObjectName("ChatBubbleBodyLabel")
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setStyleSheet(
            f"""
            QLabel#ChatBubbleBodyLabel {{
                color: {text_color};
                background: transparent;
                font-size: 15px;
                border: none;
                padding: 0;
                margin: 0;
            }}
            """
        )
        label.setText(text or " ")
        return label

    def _inner_text_width(self, bubble_width: int) -> int:
        margins = self.layout().contentsMargins()
        return max(80, bubble_width - margins.left() - margins.right())

    def _frame_vertical_margins(self) -> int:
        m = self.layout().contentsMargins()
        return m.top() + m.bottom()

    def _plain_label_height(self, label: QLabel, inner_w: int) -> int:
        """多行纯文本高度：boundingRect + heightForWidth 取较大值。"""
        text = label.text() or " "
        label.setWordWrap(True)
        label.setFixedWidth(inner_w)
        metrics = label.fontMetrics()
        rect = metrics.boundingRect(
            QRect(0, 0, inner_w, 0),
            int(Qt.TextFlag.TextWordWrap),
            text,
        )
        hfw = label.heightForWidth(inner_w)
        return max(hfw, rect.height(), metrics.lineSpacing()) + _BUBBLE_HEIGHT_SLACK

    def content_height_for_width(self, bubble_width: int) -> int:
        inner_w = self._inner_text_width(bubble_width)
        vm = self._frame_vertical_margins()
        if isinstance(self._body, _ImageBubbleBody):
            self._body.reflow_width(bubble_width)
            body_h = max(_IMG_PLACEHOLDER_H, self._body.content_height_for_width(bubble_width))
            return body_h + vm
        if isinstance(self._body, QTextBrowser):
            doc = self._body.document()
            doc.setTextWidth(inner_w)
            doc_h = int(doc.size().height())
            min_h = 48 if "<img" in (self._body.toHtml() or "").lower() else 24
            return max(min_h, doc_h) + vm + _BUBBLE_HEIGHT_SLACK
        return self._plain_label_height(self._body, inner_w) + vm

    def reflow(self, bubble_width: int) -> int:
        w = min(_BUBBLE_MAX_W, max(120, bubble_width))
        self.setMaximumWidth(w)
        inner_w = self._inner_text_width(w)
        h = self.content_height_for_width(w)
        vm = self._frame_vertical_margins()
        body_h = max(24, h - vm)
        if isinstance(self._body, QLabel):
            self._body.setFixedSize(inner_w, body_h)
        elif isinstance(self._body, QTextBrowser):
            self._body.setFixedWidth(inner_w)
            self._body.setMinimumHeight(body_h)
            self._body.setMaximumHeight(body_h)
        elif isinstance(self._body, _ImageBubbleBody):
            self._body.setMinimumHeight(body_h)
        self.setFixedHeight(h)
        return h


def _frame_image_url(
    content_type: Optional[str], image_url: Optional[str]
) -> Optional[str]:
    ct = (content_type or "text").strip().lower()
    url = (image_url or "").strip()
    return url if ct == "image" and url else None


class ChatMessageBubbleWidget(QWidget):
    """单条聊天消息行（头像 + 箭头 + 气泡 + 时间）。"""

    def __init__(
        self,
        *,
        sender_type: str,
        content: str,
        timestamp: Any,
        buyer_letter: str = "买",
        content_type: Optional[str] = None,
        image_url: Optional[str] = None,
        is_read: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("ChatMessageBubbleWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._bubble_frames: list[_BubbleFrame] = []

        ts = _format_timestamp(timestamp)
        st = (sender_type or "").strip().lower()

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 4, 12, 4)
        root.setSpacing(8)

        if st == "system":
            self._build_system(root, content, content_type, image_url, ts)
        elif st in ("customer", "ai"):
            self._build_incoming(root, st, content, content_type, image_url, ts, buyer_letter)
        else:
            self._build_outgoing(root, content, content_type, image_url, ts, is_read)

    def _track_bubble(self, bubble: _BubbleFrame) -> _BubbleFrame:
        self._bubble_frames.append(bubble)
        return bubble

    def _build_system(
        self,
        root: QHBoxLayout,
        content: str,
        content_type: Optional[str],
        image_url: Optional[str],
        ts: str,
    ) -> None:
        root.addStretch(1)
        fmt, body = _build_body(
            content,
            content_type=content_type,
            image_url=image_url,
            text_color=SYSTEM_TEXT,
        )
        bubble = self._track_bubble(
            _BubbleFrame(
                side="system",
                text_format=fmt,
                text=body,
                text_color=SYSTEM_TEXT,
                image_url=_frame_image_url(content_type, image_url),
            )
        )
        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(bubble, 0, Qt.AlignmentFlag.AlignHCenter)
        if ts:
            col.addWidget(self._time_label(ts, Qt.AlignmentFlag.AlignHCenter))
        wrap = QWidget()
        wrap.setLayout(col)
        root.addWidget(wrap, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addStretch(1)

    def _build_incoming(
        self,
        root: QHBoxLayout,
        sender_type: str,
        content: str,
        content_type: Optional[str],
        image_url: Optional[str],
        ts: str,
        buyer_letter: str,
    ) -> None:
        avatar = _avatar_label(
            "AI" if sender_type == "ai" else buyer_letter,
            "#4C87EB" if sender_type == "ai" else "#FF6B6B",
        )
        fmt, body = _build_body(
            content, content_type=content_type, image_url=image_url, text_color=OTHER_TEXT
        )

        row = QHBoxLayout()
        row.setSpacing(0)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(_BubbleArrow(pointing="left", color=OTHER_BUBBLE), 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(
            self._track_bubble(
                _BubbleFrame(
                    side="left",
                    text_format=fmt,
                    text=body,
                    text_color=OTHER_TEXT,
                    image_url=_frame_image_url(content_type, image_url),
                )
            ),
            0,
            Qt.AlignmentFlag.AlignTop,
        )

        col = QVBoxLayout()
        col.setSpacing(4)
        col.setContentsMargins(0, 0, 0, 0)
        col.addLayout(row)
        if ts:
            col.addWidget(self._time_label(ts, Qt.AlignmentFlag.AlignLeft, pad_left=10))

        col_widget = QWidget()
        col_widget.setObjectName("ChatBubbleIncomingCol")
        col_widget.setLayout(col)
        col_widget.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )

        root.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
        root.addWidget(col_widget, 0, Qt.AlignmentFlag.AlignTop)
        root.addStretch(1)

    def _build_outgoing(
        self,
        root: QHBoxLayout,
        content: str,
        content_type: Optional[str],
        image_url: Optional[str],
        ts: str,
        is_read: bool,
    ) -> None:
        fmt, body = _build_body(
            content, content_type=content_type, image_url=image_url, text_color=SELF_TEXT
        )

        row = QHBoxLayout()
        row.setSpacing(0)
        row.addWidget(
            self._track_bubble(
                _BubbleFrame(
                    side="right",
                    text_format=fmt,
                    text=body,
                    text_color=SELF_TEXT,
                    image_url=_frame_image_url(content_type, image_url),
                )
            ),
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        row.addWidget(_BubbleArrow(pointing="right", color=SELF_BUBBLE), 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(4)
        col.setContentsMargins(0, 0, 0, 0)
        col.addLayout(row, 0)
        if ts:
            col.addWidget(
                self._time_label(
                    f"{ts}  客服",
                    Qt.AlignmentFlag.AlignRight,
                    pad_right=10,
                )
            )

        col_widget = QWidget()
        col_widget.setObjectName("ChatBubbleOutgoingCol")
        col_widget.setLayout(col)
        col_widget.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )

        root.addStretch(1)
        root.addWidget(col_widget, 0, Qt.AlignmentFlag.AlignTop)
        root.addWidget(_avatar_label("我", "#22C55E"), 0, Qt.AlignmentFlag.AlignTop)

    def _time_label(
        self,
        text: str,
        align: Qt.AlignmentFlag,
        *,
        pad_left: int = 0,
        pad_right: int = 0,
    ) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("ChatBubbleTime")
        lbl.setAlignment(align)
        lbl.setStyleSheet(
            f"QLabel#ChatBubbleTime {{ color: {TIME_TEXT}; font-size: 11px; "
            f"padding-left: {pad_left}px; padding-right: {pad_right}px; background: transparent; }}"
        )
        return lbl

    def reflow(self, list_width: int) -> int:
        """按列表可用宽度重算气泡高度（窗口缩放后调用）。"""
        list_width = max(list_width, 200)
        bubble_w = min(_BUBBLE_MAX_W, max(160, list_width - 100))
        for frame in self._bubble_frames:
            frame.reflow(bubble_w)
        self.layout().activate()
        self.adjustSize()
        content_h = max(self.layout().sizeHint().height(), 48)
        total_h = content_h + _ITEM_HEIGHT_SLACK
        self.setFixedSize(list_width, total_h)
        return total_h


def _sync_list_item_widget(
    msg_list: QListWidget, item: QListWidgetItem, widget: ChatMessageBubbleWidget, list_w: int, h: int
) -> None:
    """QListWidget 兼容路径（已弃用，请用 reflow_message_widgets）。"""
    item.setSizeHint(QSize(list_w, h))
    msg_list.setItemWidget(item, widget)
    widget.setFixedSize(list_w, h)
    widget.updateGeometry()
    widget.update()


def reflow_message_widgets(
    container: QWidget, layout: QVBoxLayout, list_w: int = 0
) -> None:
    """重排滚动区内所有消息 widget（避免 QListWidget 叠加渲染）。"""
    if list_w <= 0:
        parent = container.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                list_w = max(parent.viewport().width(), 320)
                break
            parent = parent.parentWidget()
        if list_w <= 0:
            list_w = max(container.width(), 320)
    for i in range(layout.count()):
        lay_item = layout.itemAt(i)
        if lay_item is None:
            continue
        widget = lay_item.widget()
        if not isinstance(widget, ChatMessageBubbleWidget):
            continue
        h = widget.reflow(list_w)
        widget.setFixedWidth(list_w)
        widget.setFixedHeight(h)
        widget.updateGeometry()
    container.adjustSize()
    container.update()


def reflow_message_list_items(msg_list: QListWidget) -> None:
    """QListWidget 兼容重排（遗留）。"""
    list_w = max(msg_list.viewport().width(), 320)
    model = msg_list.model()
    for i in range(msg_list.count()):
        item = msg_list.item(i)
        if item is None:
            continue
        widget = msg_list.itemWidget(item)
        if not isinstance(widget, ChatMessageBubbleWidget):
            continue
        h = widget.reflow(list_w)
        item.setSizeHint(QSize(list_w, h))
        widget.setFixedSize(list_w, h)
        widget.updateGeometry()
        if model is not None:
            idx = model.index(i, 0)
            model.dataChanged.emit(idx, idx)
    msg_list.doItemsLayout()
    msg_list.viewport().update()
    msg_list.update()


def make_chat_message_widget(
    *,
    sender_type: str,
    content: str,
    timestamp: Any,
    buyer_letter: str = "买",
    content_type: Optional[str] = None,
    image_url: Optional[str] = None,
    is_read: bool = True,
    list_width: int = 0,
) -> ChatMessageBubbleWidget:
    widget = ChatMessageBubbleWidget(
        sender_type=sender_type,
        content=content,
        timestamp=timestamp,
        buyer_letter=buyer_letter,
        content_type=content_type,
        image_url=image_url,
        is_read=is_read,
    )
    w = max(list_width, 320)
    h = widget.reflow(w)
    widget.setFixedSize(w, h)
    return widget


def make_chat_message_item(
    *,
    sender_type: str,
    content: str,
    timestamp: Any,
    buyer_letter: str = "买",
    content_type: Optional[str] = None,
    image_url: Optional[str] = None,
    is_read: bool = True,
    list_width: int = 0,
) -> tuple[QListWidgetItem, ChatMessageBubbleWidget]:
    widget = make_chat_message_widget(
        sender_type=sender_type,
        content=content,
        timestamp=timestamp,
        buyer_letter=buyer_letter,
        content_type=content_type,
        image_url=image_url,
        is_read=is_read,
        list_width=list_width,
    )
    item = QListWidgetItem()
    item.setFlags(Qt.ItemFlag.NoItemFlags)
    w = max(list_width, 320)
    item.setSizeHint(QSize(w, widget.height()))
    return item, widget
