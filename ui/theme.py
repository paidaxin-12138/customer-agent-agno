"""
Customer-Agent 统一深色 SaaS 主题

应用启动时调用 ``apply_theme(app)``；样式来自 ``dark_theme.qss``。
"""
from __future__ import annotations

from PyQt6.QtGui import QFont, QPalette, QColor
from PyQt6.QtWidgets import QApplication, QStyleFactory

from qfluentwidgets import setThemeColor

from ui import apple_ui_tokens as tokens
from ui.dark_theme_loader import load_dark_theme_qss
from ui.fluent_button_styles import fluent_icon_button_qss
from ui.message_box_theme import install_themed_message_boxes

BG_PRIMARY = tokens.BG_PRIMARY
BG_SECONDARY = tokens.BG_SECONDARY
BG_TERTIARY = tokens.BG_TERTIARY
TEXT_PRIMARY = tokens.TEXT_PRIMARY
TEXT_SECONDARY = tokens.TEXT_SECONDARY
TEXT_TERTIARY = tokens.TEXT_TERTIARY
TEXT_MUTED = tokens.TEXT_MUTED
ACCENT = tokens.ACCENT
BORDER = tokens.BORDER
SUCCESS = tokens.SUCCESS
ERROR = tokens.ERROR
WARNING = tokens.WARNING


def apply_theme(app: QApplication) -> None:
    """应用全局 QSS + 调色板 + Inter 字体 + QFluent 强调色。"""
    if "Fusion" in QStyleFactory.keys():
        app.setStyle(QStyleFactory.create("Fusion"))
    setThemeColor(QColor(tokens.ACCENT_FILL), save=False)
    app.setStyleSheet(load_dark_theme_qss() + fluent_icon_button_qss())
    install_themed_message_boxes()

    font = QFont()
    font.setFamilies(
        [
            "Inter",
            "SF Pro Text",
            "PingFang SC",
            "Helvetica Neue",
            "Segoe UI",
            "Roboto",
            "Microsoft YaHei",
        ]
    )
    font.setPointSize(13)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(tokens.BG_PRIMARY))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(tokens.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Base, QColor(tokens.BG_TERTIARY))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(tokens.BG_ELEVATED))
    palette.setColor(QPalette.ColorRole.Text, QColor(tokens.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Button, QColor(tokens.BG_ELEVATED))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(tokens.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(tokens.ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(tokens.BG_PRIMARY))
    palette.setColor(QPalette.ColorRole.Link, QColor(tokens.ACCENT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(255, 255, 255, 128))
    app.setPalette(palette)


__all__ = [
    "ACCENT",
    "BG_PRIMARY",
    "BG_SECONDARY",
    "BG_TERTIARY",
    "BORDER",
    "ERROR",
    "SUCCESS",
    "TEXT_MUTED",
    "TEXT_PRIMARY",
    "TEXT_SECONDARY",
    "TEXT_TERTIARY",
    "WARNING",
    "apply_theme",
    "tokens",
]
