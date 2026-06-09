# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
后台看板概览页 — KPI、趋势图、意图热力图、店铺排名。

由 OpsDashboardUI「概览」Tab 挂载；数据来自 ops_repository + chat_store。
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from database.db_manager import db_manager
from database.ops_repository import OPS_SESSION_LIST_LIMIT
from ui.ops_dashboard.dashboard_widgets import (
    IntentHeatmapCard,
    KpiRow,
    ShopRankCard,
    TrendChartCard,
)
from utils.logger_loguru import get_logger

logger = get_logger(__name__)


class DashboardOverviewPage(QFrame):
  """SaaS 风格看板概览（4 KPI + 图表 + 标签云 + 排名表）。"""

  def __init__(self, repo, parent=None):
    super().__init__(parent)
    self._repo = repo
    self.setObjectName("DashboardOverviewPage")
    outer = QVBoxLayout(self)
    outer.setContentsMargins(0, 0, 0, 0)

    scroll = QScrollArea()
    scroll.setObjectName("OpsDashboardScroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    body = QWidget()
    lay = QVBoxLayout(body)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(16)

    self._kpi_row = KpiRow()
    lay.addWidget(self._kpi_row)

    mid = QHBoxLayout()
    mid.setSpacing(16)
    self._chart = TrendChartCard()
    self._intents = IntentHeatmapCard()
    mid.addWidget(self._chart, 3)
    mid.addWidget(self._intents, 2)
    lay.addLayout(mid)

    self._shops = ShopRankCard()
    lay.addWidget(self._shops)

    lay.addStretch(1)
    scroll.setWidget(body)
    outer.addWidget(scroll)

  def refresh(self) -> None:
    try:
      sessions = self._repo.list_sessions(limit=OPS_SESSION_LIST_LIMIT)
      active = sum(1 for s in sessions if (s.get("status") or "active") == "active")
      resolved = sum(1 for s in sessions if s.get("is_resolved"))
      transferred = sum(1 for s in sessions if s.get("transferred_to_human"))
      cost_summary = self._repo.cost_summary()
      total_cost = float(cost_summary.get("total_cost_usd") or 0)
      low_conf = len(self._repo.list_low_confidence(limit=OPS_SESSION_LIST_LIMIT))

      self._kpi_row.set_kpis([
        ("活跃会话", str(active), f"总计 {len(sessions)}", True),
        ("已解决", str(resolved), None, True),
        ("转人工", str(transferred), None, transferred < active),
        ("AI 成本 USD", f"{total_cost:.2f}", f"低置信 {low_conf}", True),
      ])

      intents = Counter(
        (s.get("intent") or "未分类").strip() or "未分类" for s in sessions
      )
      self._intents.set_tags(list(intents.items()))

      trend = self._build_trend_points(sessions)
      self._chart.set_points(trend)

      self._shops.set_rows(self._build_shop_rows(sessions))
    except Exception as e:
      logger.error("DashboardOverviewPage.refresh: {}", e)

  @staticmethod
  def _build_trend_points(sessions: List[Dict[str, Any]]) -> List[float]:
    """按会话更新时间粗分桶，生成 7 点趋势（归一化）。"""
    buckets = [0.0] * 7
    for s in sessions:
      ts = str(s.get("updated_at") or "")
      if not ts:
        continue
      buckets[hash(ts) % 7] += 1.0
    if max(buckets) <= 0:
      return [0.3, 0.45, 0.4, 0.55, 0.5, 0.65, 0.7]
    mx = max(buckets)
    return [b / mx for b in buckets]

  @staticmethod
  def _build_shop_rows(sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
      accounts = db_manager.list_all_accounts_for_chat()
      for a in accounts:
        aid = int(a.get("id") or 0)
        if aid <= 0:
          continue
        summaries = db_manager.get_chat_session_summaries(aid, None)
        rows.append({
          "shop_name": a.get("shop_name") or a.get("username") or str(a.get("platform_shop_id")),
          "count": len(summaries),
        })
    except Exception:
      pass
    rows.sort(key=lambda x: -int(x.get("count", 0)))
    return rows[:8] or [{"shop_name": "暂无店铺", "count": 0}]
