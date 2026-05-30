"""实时聊天消息气泡（QListWidget + 自定义 QWidget，QPainter 三角箭头）。"""
from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any, Literal, Optional, Tuple

from PyQt6.QtCore import Qt, QSize, QPoint
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QSizePolicy,
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
    if ct in ("image", "video") and (image_url or "").strip():
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

    if ct == "image" and url:
        body = format_chat_bubble_html(url) or html.escape(raw or "[图片]")
        return Qt.TextFormat.RichText, _colorize_html(body, text_color)
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
    """圆角气泡容器（背景/边框在 Frame 上，文字在内部 QLabel）。"""

    def __init__(
        self,
        *,
        side: Literal["left", "right", "system"],
        text_format: Qt.TextFormat,
        text: str,
        text_color: str,
        parent=None,
    ):
        super().__init__(parent)
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

        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setTextFormat(text_format)
        self._label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._label.setStyleSheet(
            f"QLabel {{ color: {text_color}; background: transparent; "
            f"font-size: 15px; border: none; padding: 0; margin: 0; }}"
        )
        if text_format == Qt.TextFormat.RichText:
            self._label.setTextInteractionFlags(
                Qt.TextInteractionFlag.LinksAccessibleByMouse
                | Qt.TextInteractionFlag.TextSelectableByMouse
            )
            self._label.setOpenExternalLinks(True)
            self._label.setText(text)
        else:
            self._label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            self._label.setText(text or " ")
        lay.addWidget(self._label)


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
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

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
        bubble = _BubbleFrame(side="system", text_format=fmt, text=body, text_color=SYSTEM_TEXT)
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
        avatar = _avatar_label("AI" if sender_type == "ai" else buyer_letter,
                               "#4C87EB" if sender_type == "ai" else "#FF6B6B")
        fmt, body = _build_body(
            content, content_type=content_type, image_url=image_url, text_color=OTHER_TEXT
        )

        row = QHBoxLayout()
        row.setSpacing(0)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(_BubbleArrow(pointing="left", color=OTHER_BUBBLE), 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(
            _BubbleFrame(side="left", text_format=fmt, text=body, text_color=OTHER_TEXT),
            0,
            Qt.AlignmentFlag.AlignTop,
        )

        col = QVBoxLayout()
        col.setSpacing(4)
        col.setContentsMargins(0, 0, 0, 0)
        col.addLayout(row)
        if ts:
            col.addWidget(self._time_label(ts, Qt.AlignmentFlag.AlignLeft, pad_left=10))

        root.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(col, 0)
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
            _BubbleFrame(side="right", text_format=fmt, text=body, text_color=SELF_TEXT),
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        row.addWidget(_BubbleArrow(pointing="right", color=SELF_BUBBLE), 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(4)
        col.setContentsMargins(0, 0, 0, 0)
        col.addLayout(row, 0)
        if ts:
            read_hint = "已读" if is_read else "未读"
            col.addWidget(
                self._time_label(f"{ts}  客服  {read_hint}", Qt.AlignmentFlag.AlignRight, pad_right=10)
            )

        root.addStretch(1)
        root.addLayout(col, 0)
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

    def sizeHint(self) -> QSize:  # noqa: N802
        self.layout().activate()
        h = self.layout().sizeHint().height()
        return QSize(0, max(h, 48))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        lw = self.parentWidget()
        if lw is not None and hasattr(lw, "itemWidget"):
            for i in range(lw.count()):
                it = lw.item(i)
                if lw.itemWidget(it) is self:
                    self.layout().activate()
                    h = self.layout().sizeHint().height()
                    it.setSizeHint(QSize(lw.viewport().width(), max(h, 48)))
                    break


def make_chat_message_item(
    *,
    sender_type: str,
    content: str,
    timestamp: Any,
    buyer_letter: str = "买",
    content_type: Optional[str] = None,
    image_url: Optional[str] = None,
    is_read: bool = True,
) -> tuple[QListWidgetItem, ChatMessageBubbleWidget]:
    widget = ChatMessageBubbleWidget(
        sender_type=sender_type,
        content=content,
        timestamp=timestamp,
        buyer_letter=buyer_letter,
        content_type=content_type,
        image_url=image_url,
        is_read=is_read,
    )
    item = QListWidgetItem()
    item.setFlags(Qt.ItemFlag.NoItemFlags)
    item.setSizeHint(widget.sizeHint())
    return item, widget
