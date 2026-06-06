"""卡片内紧凑操作按钮（与 dark_theme.qss #CardActionButton 配套）。"""
from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QPushButton, QWidget


def setup_card_action_button(
    btn: QWidget,
    *,
    width: int = 84,
    role: str | None = None,
) -> None:
    """统一卡片内图标+文字按钮尺寸，避免与全局 QSS min-height 冲突。"""
    btn.setObjectName("CardActionButton")
    btn.setFixedSize(width, 32)
    if hasattr(btn, "setIconSize"):
        btn.setIconSize(QSize(14, 14))
    if role:
        btn.setProperty("cardRole", role)
    style = btn.style()
    style.unpolish(btn)
    style.polish(btn)
