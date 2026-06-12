# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""QListView + QStyledItemDelegate 聊天消息列表（替代 setItemWidget / QVBoxLayout 方案）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from PyQt6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTextDocument,
    QTextOption,
)
from PyQt6.QtWidgets import QListView, QStyledItemDelegate, QWidget

from ui.widgets.chat_bubble_widgets import (
    OTHER_BUBBLE,
    OTHER_BORDER,
    OTHER_TEXT,
    SELF_ARROW,
    SELF_BUBBLE,
    SELF_BUBBLE_BORDER,
    SELF_TEXT,
    SYSTEM_BG,
    SYSTEM_TEXT,
    TIME_TEXT,
    _BUBBLE_MAX_W,
    _IMG_MAX_H,
    _IMG_MAX_W,
    _IMG_PLACEHOLDER_H,
    _build_body,
    _format_timestamp,
    _frame_image_url,
)
from utils.chat_image_cache import get_chat_image_cache

_ROW_V_MARGIN = 4
_ROW_H_MARGIN = 12
_AVATAR_SIZE = 36
_ARROW_W = 10
_ARROW_H = 14
_BUBBLE_PAD_H = 12
_BUBBLE_PAD_V = 8
_BUBBLE_RADIUS = 18
_TIME_H = 18
_LOADING_ROW_H = 44


def _scale_chat_image(pm: QPixmap, max_w: int, max_h: int) -> QPixmap:
    """按最大宽高等比缩放聊天图片。"""
    if pm.isNull():
        return pm
    cap_w = max(1, min(int(max_w), _IMG_MAX_W))
    cap_h = max(1, int(max_h))
    return pm.scaled(
        cap_w,
        cap_h,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _image_bubble_dimensions(
    pm: Optional[QPixmap],
    *,
    list_inner_max: int,
    loaded: bool,
) -> tuple[int, int]:
    """返回图片气泡 (宽, 高)，宽高度贴合实际图片而非文本最大宽。"""
    pad_w = _BUBBLE_PAD_H * 2
    pad_h = _BUBBLE_PAD_V * 2
    max_inner_w = min(max(80, list_inner_max - pad_w), _IMG_MAX_W)
    if loaded and pm is not None and not pm.isNull():
        scaled = _scale_chat_image(pm, max_inner_w, _IMG_MAX_H)
        bubble_w = max(80, scaled.width()) + pad_w
        bubble_h = max(_IMG_PLACEHOLDER_H - pad_h, scaled.height()) + pad_h
        return bubble_w, bubble_h
    placeholder_w = min(180, list_inner_max)
    return placeholder_w, _IMG_PLACEHOLDER_H + pad_h


@dataclass
class ChatMessageRow:
    msg_id: int = 0
    sender_type: str = "customer"
    content: str = ""
    timestamp: Any = ""
    content_type: Optional[str] = None
    image_url: Optional[str] = None
    is_read: bool = True
    buyer_letter: str = "买"
    is_loading_placeholder: bool = False


class ChatMessageListModel(QAbstractListModel):
    RowRole = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: List[ChatMessageRow] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: N802
        if not index.isValid() or index.row() < 0 or index.row() >= len(self._rows):
            return None
        if role == self.RowRole:
            return self._rows[index.row()]
        return None

    def clear_rows(self) -> None:
        if not self._rows:
            return
        self.beginResetModel()
        self._rows.clear()
        self.endResetModel()

    def set_rows(self, rows: List[ChatMessageRow]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def append_rows(self, rows: List[ChatMessageRow]) -> None:
        if not rows:
            return
        first = len(self._rows)
        last = first + len(rows) - 1
        self.beginInsertRows(QModelIndex(), first, last)
        self._rows.extend(rows)
        self.endInsertRows()

    def prepend_rows(self, rows: List[ChatMessageRow]) -> None:
        if not rows:
            return
        self.beginInsertRows(QModelIndex(), 0, len(rows) - 1)
        self._rows = list(rows) + self._rows
        self.endInsertRows()

    def remove_loading_placeholder(self) -> None:
        if self._rows and self._rows[0].is_loading_placeholder:
            self.beginRemoveRows(QModelIndex(), 0, 0)
            self._rows.pop(0)
            self.endRemoveRows()

    def set_loading_placeholder(self, enabled: bool) -> None:
        if enabled:
            if self._rows and self._rows[0].is_loading_placeholder:
                return
            self.beginInsertRows(QModelIndex(), 0, 0)
            self._rows.insert(0, ChatMessageRow(is_loading_placeholder=True))
            self.endInsertRows()
        else:
            self.remove_loading_placeholder()

    def message_count(self) -> int:
        return sum(1 for r in self._rows if not r.is_loading_placeholder)

    def last_message_id(self) -> int:
        for row in reversed(self._rows):
            if not row.is_loading_placeholder and row.msg_id:
                return int(row.msg_id)
        return 0

    def image_urls_in_range(self, first: int, last: int) -> Set[str]:
        urls: Set[str] = set()
        for i in range(max(0, first), min(len(self._rows), last + 1)):
            row = self._rows[i]
            if row.is_loading_placeholder:
                continue
            url = _frame_image_url(row.content_type, row.image_url)
            if url:
                urls.add(url)
        return urls

    @staticmethod
    def row_from_db(
        m: Dict[str, Any],
        *,
        buyer_letter: str,
    ) -> ChatMessageRow:
        return ChatMessageRow(
            msg_id=int(m.get("id") or 0),
            sender_type=str(m.get("sender_type") or "customer"),
            content=str(m.get("content") or ""),
            timestamp=m.get("sent_at") or m.get("created_at"),
            content_type=m.get("content_type"),
            image_url=m.get("image_url"),
            is_read=bool(m.get("is_read", True)),
            buyer_letter=buyer_letter,
        )


class _BubbleMetrics:
    __slots__ = (
        "bubble_w",
        "bubble_h",
        "row_h",
        "is_system",
        "is_image",
        "image_url",
        "text_fmt",
        "text_body",
        "text_color",
        "sender_type",
        "ts",
        "buyer_letter",
    )

    def __init__(self, row: ChatMessageRow, list_w: int) -> None:
        self.sender_type = (row.sender_type or "").strip().lower()
        self.is_system = self.sender_type == "system"
        self.ts = _format_timestamp(row.timestamp)
        self.buyer_letter = row.buyer_letter or "买"
        img_url = _frame_image_url(row.content_type, row.image_url)
        self.is_image = bool(img_url)
        self.image_url = img_url or ""

        if self.is_system:
            self.text_color = SYSTEM_TEXT
        elif self.sender_type in ("customer", "ai"):
            self.text_color = OTHER_TEXT
        else:
            self.text_color = SELF_TEXT

        fmt, body = _build_body(
            row.content,
            content_type=row.content_type,
            image_url=row.image_url,
            text_color=self.text_color,
        )
        self.text_fmt = fmt
        self.text_body = body

        inner_max = min(_BUBBLE_MAX_W, max(160, list_w - 96))
        if self.is_system:
            self.bubble_w = min(inner_max, max(180, list_w - 80))
        else:
            self.bubble_w = inner_max

        if self.is_image:
            cache = get_chat_image_cache()
            pm = cache.get(self.image_url)
            loaded = pm is not None and not pm.isNull()
            self.bubble_w, self.bubble_h = _image_bubble_dimensions(
                pm,
                list_inner_max=inner_max,
                loaded=loaded,
            )
        elif self.text_fmt == Qt.TextFormat.RichText:
            doc = QTextDocument()
            doc.setDefaultFont(QFont("", 15))
            doc.setDefaultTextOption(QTextOption(Qt.AlignmentFlag.AlignLeft))
            doc.setTextWidth(max(80, self.bubble_w - _BUBBLE_PAD_H * 2))
            doc.setHtml(self.text_body)
            self.bubble_h = int(doc.size().height()) + _BUBBLE_PAD_V * 2 + 4
        else:
            fm = QFontMetrics(QFont("", 15))
            inner_w = max(80, self.bubble_w - _BUBBLE_PAD_H * 2)
            rect = fm.boundingRect(
                QRect(0, 0, inner_w, 0),
                int(Qt.TextFlag.TextWordWrap),
                self.text_body or " ",
            )
            self.bubble_h = max(fm.lineSpacing(), rect.height()) + _BUBBLE_PAD_V * 2 + 4

        meta_h = _TIME_H if self.ts else 0
        body_h = max(_AVATAR_SIZE, self.bubble_h + _ARROW_H // 2)
        self.row_h = body_h + meta_h + _ROW_V_MARGIN * 2


def _draw_arrow(
    painter: QPainter,
    x: int,
    y: int,
    *,
    pointing: str,
    color: QColor,
) -> None:
    painter.save()
    painter.setPen(QPen(Qt.PenStyle.NoPen))
    painter.setBrush(QBrush(color))
    if pointing == "left":
        pts = [QPoint(x + 9, y + 7), QPoint(x, y + 1), QPoint(x, y + 13)]
    else:
        pts = [QPoint(x, y + 7), QPoint(x + 9, y + 1), QPoint(x + 9, y + 13)]
    painter.drawPolygon(pts)
    painter.restore()


def _draw_round_rect(painter: QPainter, rect: QRect, radius: int, color: QColor, border: QColor) -> None:
    path = QPainterPath()
    path.addRoundedRect(rect.x(), rect.y(), rect.width(), rect.height(), radius, radius)
    painter.fillPath(path, QBrush(color))
    if border.alpha() > 0:
        painter.setPen(QPen(border, 1))
        painter.drawPath(path)


class ChatMessageItemDelegate(QStyledItemDelegate):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._list_width = 360
        cache = get_chat_image_cache()
        cache.pixmap_loaded.connect(self._on_pixmap_loaded)
        cache.pixmap_failed.connect(self._on_pixmap_loaded)

    def set_list_width(self, width: int) -> None:
        w = max(320, int(width))
        if w != self._list_width:
            self._list_width = w

    def _on_pixmap_loaded(self, _url: str) -> None:
        view = self.parent()
        if isinstance(view, ChatMessageListView):
            view.relayout_items()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        row = index.data(ChatMessageListModel.RowRole)
        if not isinstance(row, ChatMessageRow):
            return QSize(self._list_width, 48)
        if row.is_loading_placeholder:
            return QSize(self._list_width, _LOADING_ROW_H)
        metrics = _BubbleMetrics(row, self._list_width)
        return QSize(self._list_width, metrics.row_h)

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: N802
        row = index.data(ChatMessageListModel.RowRole)
        if not isinstance(row, ChatMessageRow):
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect

        if row.is_loading_placeholder:
            painter.setPen(QColor(TIME_TEXT))
            painter.drawText(
                rect,
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                "加载中…",
            )
            painter.restore()
            return

        metrics = _BubbleMetrics(row, self._list_width)
        st = metrics.sender_type

        if metrics.is_image and metrics.image_url:
            cache = get_chat_image_cache()
            if cache.get(metrics.image_url) is None and not cache.is_failed(metrics.image_url):
                cache.request(metrics.image_url)

        y0 = rect.top() + _ROW_V_MARGIN
        if metrics.is_system:
            self._paint_system(painter, rect, metrics, y0)
        elif st in ("customer", "ai"):
            self._paint_incoming(painter, rect, metrics, y0, st)
        else:
            self._paint_outgoing(painter, rect, metrics, y0)
        painter.restore()

    def _paint_system(self, painter: QPainter, rect: QRect, m: _BubbleMetrics, y0: int) -> None:
        bubble_rect = QRect(
            rect.center().x() - m.bubble_w // 2,
            y0,
            m.bubble_w,
            m.bubble_h,
        )
        _draw_round_rect(
            painter,
            bubble_rect,
            _BUBBLE_RADIUS,
            QColor(SYSTEM_BG),
            QColor(0, 0, 0, 0),
        )
        self._paint_bubble_body(painter, bubble_rect, m)
        if m.ts:
            painter.setPen(QColor(TIME_TEXT))
            painter.drawText(
                QRect(rect.left(), bubble_rect.bottom() + 2, rect.width(), _TIME_H),
                int(Qt.AlignmentFlag.AlignHCenter),
                m.ts,
            )

    def _paint_incoming(
        self, painter: QPainter, rect: QRect, m: _BubbleMetrics, y0: int, st: str
    ) -> None:
        letter = "AI" if st == "ai" else (m.buyer_letter or "买")
        color = QColor("#4C87EB" if st == "ai" else "#FF6B6B")
        av_rect = QRect(rect.left() + _ROW_H_MARGIN, y0, _AVATAR_SIZE, _AVATAR_SIZE)
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        painter.drawEllipse(av_rect)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(av_rect, int(Qt.AlignmentFlag.AlignCenter), letter[:2])

        x = av_rect.right() + 8
        arrow_y = y0 + 4
        _draw_arrow(painter, x, arrow_y, pointing="left", color=QColor(OTHER_BUBBLE))
        bubble_x = x + _ARROW_W
        bubble_rect = QRect(bubble_x, y0, m.bubble_w, m.bubble_h)
        _draw_round_rect(
            painter,
            bubble_rect,
            _BUBBLE_RADIUS,
            QColor(OTHER_BUBBLE),
            QColor(OTHER_BORDER),
        )
        self._paint_bubble_body(painter, bubble_rect, m)
        if m.ts:
            painter.setPen(QColor(TIME_TEXT))
            painter.drawText(
                QRect(bubble_x + 10, bubble_rect.bottom() + 2, m.bubble_w, _TIME_H),
                int(Qt.AlignmentFlag.AlignLeft),
                m.ts,
            )

    def _paint_outgoing(self, painter: QPainter, rect: QRect, m: _BubbleMetrics, y0: int) -> None:
        bubble_x = rect.right() - _ROW_H_MARGIN - m.bubble_w - _ARROW_W
        bubble_rect = QRect(bubble_x, y0, m.bubble_w, m.bubble_h)
        _draw_round_rect(
            painter,
            bubble_rect,
            _BUBBLE_RADIUS,
            QColor(SELF_BUBBLE),
            QColor(SELF_BUBBLE_BORDER),
        )
        self._paint_bubble_body(painter, bubble_rect, m)
        arrow_x = bubble_rect.right()
        _draw_arrow(painter, arrow_x, y0 + 4, pointing="right", color=QColor(SELF_ARROW))
        if m.ts:
            painter.setPen(QColor(TIME_TEXT))
            painter.drawText(
                QRect(bubble_x, bubble_rect.bottom() + 2, m.bubble_w + _ARROW_W, _TIME_H),
                int(Qt.AlignmentFlag.AlignRight),
                f"{m.ts}  客服",
            )

    def _paint_bubble_body(self, painter: QPainter, bubble_rect: QRect, m: _BubbleMetrics) -> None:
        inner = bubble_rect.adjusted(_BUBBLE_PAD_H, _BUBBLE_PAD_V, -_BUBBLE_PAD_H, -_BUBBLE_PAD_V)
        if m.is_image and m.image_url:
            cache = get_chat_image_cache()
            pm = cache.get(m.image_url)
            if pm is not None and not pm.isNull():
                scaled = _scale_chat_image(pm, inner.width(), _IMG_MAX_H)
                img_x = inner.left() + max(0, (inner.width() - scaled.width()) // 2)
                img_rect = QRect(
                    img_x,
                    inner.top(),
                    scaled.width(),
                    scaled.height(),
                )
                painter.drawPixmap(img_rect, scaled)
            else:
                painter.setPen(QColor(m.text_color))
                fail = cache.is_failed(m.image_url)
                painter.drawText(
                    inner,
                    int(Qt.AlignmentFlag.AlignCenter),
                    "图片加载失败" if fail else "加载中…",
                )
            return

        painter.setPen(QColor(m.text_color))
        font = QFont("", 15)
        painter.setFont(font)
        if m.text_fmt == Qt.TextFormat.RichText:
            doc = QTextDocument()
            doc.setDefaultFont(font)
            doc.setTextWidth(inner.width())
            doc.setHtml(m.text_body)
            painter.translate(inner.topLeft())
            doc.drawContents(painter)
            painter.translate(-inner.topLeft())
        else:
            painter.drawText(
                inner,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
                m.text_body or " ",
            )


class ChatMessageListView(QListView):
    """高性能消息列表：委托绘制 + 分页加载信号。"""

    request_load_older = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("LiveChatMsgList")
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setUniformItemSizes(False)
        self.setSpacing(2)
        self.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet(
            """
            QListView#LiveChatMsgList {
                background: transparent;
                border: none;
                outline: none;
            }
            """
        )

        self._model = ChatMessageListModel(self)
        self.setModel(self._model)
        self._delegate = ChatMessageItemDelegate(self)
        self.setItemDelegate(self._delegate)

        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.verticalScrollBar().valueChanged.connect(self._prune_image_cache)

    @property
    def message_model(self) -> ChatMessageListModel:
        return self._model

    def set_list_width(self, width: int) -> None:
        self._delegate.set_list_width(width)
        self.viewport().update()

    def clear_messages(self) -> None:
        self._model.clear_rows()
        get_chat_image_cache().clear()

    def append_messages(self, rows: List[ChatMessageRow]) -> None:
        self._model.append_rows(rows)

    def prepend_messages(self, rows: List[ChatMessageRow]) -> None:
        self._model.prepend_rows(rows)

    def set_messages(self, rows: List[ChatMessageRow]) -> None:
        self._model.set_rows(rows)

    def message_count(self) -> int:
        return self._model.message_count()

    def last_message_id(self) -> int:
        return self._model.last_message_id()

    def set_loading_placeholder(self, enabled: bool) -> None:
        self._model.set_loading_placeholder(enabled)

    def scroll_to_bottom(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def relayout_items(self) -> None:
        """图片加载后重新计算各行高度，避免气泡被裁切。"""
        self.doItemsLayout()
        self.viewport().update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.set_list_width(self.viewport().width())

    def _on_scroll(self, value: int) -> None:
        if value <= 12:
            self.request_load_older.emit()

    def _prune_image_cache(self, _value: int = 0) -> None:
        first = self.indexAt(self.viewport().rect().topLeft()).row()
        last = self.indexAt(self.viewport().rect().bottomLeft()).row()
        if first < 0:
            first = 0
        if last < 0:
            last = self._model.rowCount() - 1
        urls = self._model.image_urls_in_range(first, last)
        get_chat_image_cache().retain_only(urls)
