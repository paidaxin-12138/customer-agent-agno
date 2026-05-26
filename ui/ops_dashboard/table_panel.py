"""运营看板通用表格面板。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import CaptionLabel, PrimaryPushButton, PushButton, SubtitleLabel


class DictTableModel(QAbstractTableModel):
    def __init__(self, columns: Sequence[str], headers: Optional[Dict[str, str]] = None):
        super().__init__()
        self._columns = list(columns)
        self._headers = headers or {}
        self._rows: List[Dict[str, Any]] = []

    def set_rows(self, rows: List[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = rows or []
        self.endResetModel()

    def row_at(self, index: int) -> Optional[Dict[str, Any]]:
        if 0 <= index < len(self._rows):
            return self._rows[index]
        return None

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        row = self._rows[index.row()]
        key = self._columns[index.column()]
        val = row.get(key, "")
        if isinstance(val, bool):
            return "是" if val else "否"
        if val is None:
            return ""
        return str(val)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        key = self._columns[section]
        return self._headers.get(key, key)


class OpsTablePanel(QWidget):
    """标题 + 工具栏 + 表格。"""

    def __init__(
        self,
        title: str,
        columns: Sequence[str],
        headers: Optional[Dict[str, str]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._columns = list(columns)
        self._model = DictTableModel(columns, headers)
        self._on_refresh = None
        self._detail_label: Optional[QLabel] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel(title))
        header.addStretch()
        self.refresh_btn = PrimaryPushButton("刷新")
        self.refresh_btn.clicked.connect(self._do_refresh)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        self.table = QTableView()
        self.table.setModel(self._model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.clicked.connect(self._on_row_clicked)
        layout.addWidget(self.table, 1)

        self.detail = CaptionLabel("")
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color: #9EA6B8; font-size: 11px;")
        layout.addWidget(self.detail)

    def set_refresh_callback(self, cb) -> None:
        self._on_refresh = cb

    def set_rows(self, rows: List[Dict[str, Any]]) -> None:
        self._model.set_rows(rows)

    def selected_row(self) -> Optional[Dict[str, Any]]:
        idx = self.table.currentIndex()
        if idx.isValid():
            return self._model.row_at(idx.row())
        return None

    def _do_refresh(self) -> None:
        if self._on_refresh:
            self._on_refresh()

    def _on_row_clicked(self, index: QModelIndex) -> None:
        row = self._model.row_at(index.row())
        if row and self._detail_label:
            self.detail.setText(self._detail_formatter(row))

    def set_detail_formatter(self, fn) -> None:
        self._detail_formatter = fn

    def _default_detail(self, row: Dict[str, Any]) -> str:
        parts = [f"{k}: {v}" for k, v in row.items() if v not in (None, "")]
        return " | ".join(parts[:12])

    _detail_formatter = _default_detail
