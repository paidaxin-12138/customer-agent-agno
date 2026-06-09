# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""后台看板 SaaS 风格组件（KPI / 图表 / 标签云 / 排名表）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from ui import apple_ui_tokens as T
from ui.ops_dashboard.table_panel import configure_ops_table_scroll


class DashboardCard(QFrame):
  """玻璃风格卡片容器。"""

  def __init__(self, parent=None):
    super().__init__(parent)
    self.setProperty("class", "DashboardCard")
    self.setObjectName("DashboardCard")
    self._lay = QVBoxLayout(self)
    self._lay.setContentsMargins(24, 24, 24, 24)
    self._lay.setSpacing(12)

  def layout(self) -> QVBoxLayout:
    return self._lay


class KpiCard(DashboardCard):
  def __init__(
      self,
      title: str,
      value: str,
      trend: Optional[str] = None,
      trend_up: bool = True,
      parent=None,
  ):
    super().__init__(parent)
    t = QLabel(title)
    t.setProperty("class", "MetricTitle")
    t.setObjectName("MetricTitle")
    v = QLabel(value)
    v.setProperty("class", "MetricLabel")
    v.setObjectName("MetricLabel")
    self._lay.addWidget(t)
    self._lay.addWidget(v)
    if trend:
      tr = QLabel(trend)
      tr.setProperty("class", "MetricTrendUp" if trend_up else "MetricTrendDown")
      tr.setObjectName("MetricTrendUp" if trend_up else "MetricTrendDown")
      self._lay.addWidget(tr)
    self._lay.addStretch(1)


class TrendChartCard(DashboardCard):
  """AI Performance Trends — 简易折线图（QPainter）。"""

  def __init__(self, parent=None):
    super().__init__(parent)
    title = QLabel("AI Performance Trends")
    title.setProperty("class", "SectionTitle")
    title.setObjectName("SectionTitle")
    self._lay.addWidget(title)
    self._canvas = _TrendCanvas()
    self._canvas.setObjectName("ChartPanel")
    self._lay.addWidget(self._canvas, 1)

  def set_points(self, points: List[float]) -> None:
    self._canvas.set_points(points)


class _TrendCanvas(QWidget):
  def __init__(self):
    super().__init__()
    self.setProperty("class", "ChartPanel")
    self.setMinimumHeight(220)
    self._points: List[float] = [0.4, 0.55, 0.5, 0.72, 0.68, 0.85, 0.9]

  def set_points(self, points: List[float]) -> None:
    self._points = points or [0.0]
    self.update()

  def paintEvent(self, event) -> None:  # noqa: N802
    super().paintEvent(event)
    if not self._points:
      return
    p = QPainter(self)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    w, h = self.width(), self.height()
    pad = 28
    chart = QRectF(pad, pad, w - pad * 2, h - pad * 2)
    for i in range(5):
      y = chart.top() + chart.height() * i / 4
      p.setPen(QPen(QColor(255, 255, 255, 12), 1))
      p.drawLine(int(chart.left()), int(y), int(chart.right()), int(y))
    mx = max(self._points) or 1.0
    mn = min(self._points)
    span = max(mx - mn, 0.01)
    pts = []
    n = len(self._points)
    for i, v in enumerate(self._points):
      x = chart.left() + chart.width() * i / max(n - 1, 1)
      y = chart.bottom() - chart.height() * ((v - mn) / span)
      pts.append((x, y))
    accent = QColor(T.ACCENT)
    p.setPen(QPen(accent, 2.5))
    for i in range(1, len(pts)):
      p.drawLine(int(pts[i - 1][0]), int(pts[i - 1][1]), int(pts[i][0]), int(pts[i][1]))
    p.setBrush(accent)
    for x, y in pts:
      p.drawEllipse(int(x) - 3, int(y) - 3, 6, 6)
    p.end()


class IntentHeatmapCard(DashboardCard):
  def __init__(self, parent=None):
    super().__init__(parent)
    title = QLabel("意图热力图")
    title.setProperty("class", "SectionTitle")
    title.setObjectName("SectionTitle")
    self._lay.addWidget(title)
    self._flow = QWidget()
    self._flow_layout = QGridLayout(self._flow)
    self._flow_layout.setContentsMargins(0, 0, 0, 0)
    self._flow_layout.setHorizontalSpacing(8)
    self._flow_layout.setVerticalSpacing(8)
    self._flow_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    self._lay.addWidget(self._flow)
    self._lay.addStretch(1)
    self._cols = 4

  def set_tags(self, tags: List[tuple[str, int]], max_show: int = 12) -> None:
    while self._flow_layout.count():
      item = self._flow_layout.takeAt(0)
      if item.widget():
        item.widget().deleteLater()
    if not tags:
      self._flow_layout.addWidget(QLabel("暂无意图数据"), 0, 0)
      return
    tags = sorted(tags, key=lambda x: -x[1])[:max_show]
    top = tags[0][1] if tags else 1
    for i, (name, cnt) in enumerate(tags):
      lb = QLabel(f"{name}  {cnt}")
      hot = cnt >= top * 0.6
      lb.setProperty("class", "IntentTagHot" if hot else "IntentTag")
      lb.setObjectName("IntentTagHot" if hot else "IntentTag")
      row, col = divmod(i, self._cols)
      self._flow_layout.addWidget(lb, row, col)


class ShopRankCard(DashboardCard):
  def __init__(self, parent=None):
    super().__init__(parent)
    title = QLabel("店铺接待排名")
    title.setProperty("class", "SectionTitle")
    title.setObjectName("SectionTitle")
    self._lay.addWidget(title)
    self.table = QTableWidget(0, 4)
    self.table.setObjectName("OpsDataTable")
    self.table.setHorizontalHeaderLabels(["店铺", "会话数", "进度", "状态"])
    self.table.setCornerButtonEnabled(False)
    self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
    self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    self.table.verticalHeader().setVisible(False)
    self.table.setShowGrid(False)
    self.table.setAlternatingRowColors(True)
    configure_ops_table_scroll(self.table)
    self._lay.addWidget(self.table, 1)

  def set_rows(self, rows: List[Dict[str, Any]]) -> None:
    self.table.setRowCount(0)
    if not rows:
      return
    max_cnt = max(int(r.get("count", 0)) for r in rows) or 1
    for r in rows:
      row = self.table.rowCount()
      self.table.insertRow(row)
      self.table.setItem(row, 0, QTableWidgetItem(str(r.get("shop_name", "—"))))
      cnt = int(r.get("count", 0))
      self.table.setItem(row, 1, QTableWidgetItem(str(cnt)))
      bar = QProgressBar()
      bar.setRange(0, max_cnt)
      bar.setValue(cnt)
      bar.setTextVisible(False)
      self.table.setCellWidget(row, 2, bar)
      status = QLabel("正常" if cnt > 0 else "空闲")
      status.setObjectName("StatusBadge")
      status.setProperty("class", "StatusBadge")
      status.setProperty("status", "ok" if cnt > 0 else "warn")
      status.setAlignment(Qt.AlignmentFlag.AlignCenter)
      self.table.setCellWidget(row, 3, status)
      self.table.setRowHeight(row, 56)


class KpiRow(QWidget):
  def __init__(self, parent=None):
    super().__init__(parent)
    self._grid = QGridLayout(self)
    self._grid.setContentsMargins(0, 0, 0, 0)
    self._grid.setSpacing(16)
    self._cards: List[KpiCard] = []

  def set_kpis(self, items: List[tuple[str, str, Optional[str], bool]]) -> None:
    for c in self._cards:
      c.deleteLater()
    self._cards.clear()
    for i, (title, value, trend, up) in enumerate(items[:4]):
      card = KpiCard(title, value, trend, up)
      self._grid.addWidget(card, 0, i)
      self._cards.append(card)
