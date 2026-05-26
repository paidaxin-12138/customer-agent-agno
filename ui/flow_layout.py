"""横向排列、宽度不足时自动换行（顶栏按钮、标签区等）。"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QWidget


class FlowLayout(QLayout):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        h_spacing: int = 8,
        v_spacing: int = 8,
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_space = h_spacing
        self._v_space = v_spacing

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), dry_run=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, dry_run=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize(0, 0)
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect: QRect, *, dry_run: bool) -> int:
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        line_h = 0
        max_x = rect.x() + rect.width() - m.right()

        for item in self._items:
            wdg = item.widget()
            if wdg is None:
                continue
            hint = item.sizeHint()
            mw = max(hint.width(), item.minimumSize().width())
            mh = max(hint.height(), item.minimumSize().height())
            next_x = x + mw + self._h_space
            if next_x - self._h_space > max_x and line_h > 0:
                x = rect.x() + m.left()
                y = y + line_h + self._v_space
                next_x = x + mw + self._h_space
                line_h = 0

            if not dry_run:
                item.setGeometry(QRect(QPoint(x, y), QSize(mw, mh)))

            x = next_x
            line_h = max(line_h, mh)

        y += line_h + m.bottom()
        return y - rect.y()
