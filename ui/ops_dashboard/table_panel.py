# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""运营看板通用表格面板。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import CaptionLabel, PrimaryPushButton, PushButton, SubtitleLabel


def configure_ops_table_scroll(table: QAbstractScrollArea) -> None:
    """约束表格在父级高度内滚动，并在右侧显示垂直滚动条。"""
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)


def configure_ops_table_view(table: QTableView) -> None:
    """后台看板表格：隐藏行号/角按钮，避免深色主题下出现黑块或「假复选框」。"""
    table.setObjectName("OpsDataTable")
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setCornerButtonEnabled(False)
    table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
    table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    table.setFrameShape(QFrame.Shape.NoFrame)
    configure_ops_table_scroll(table)

    v_header = table.verticalHeader()
    v_header.setVisible(False)
    v_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    v_header.setDefaultSectionSize(48)

    h_header = table.horizontalHeader()
    h_header.setVisible(True)
    h_header.setHighlightSections(False)
    h_header.setStretchLastSection(True)
    h_header.setDefaultAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )


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
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
        configure_ops_table_view(self.table)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
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
