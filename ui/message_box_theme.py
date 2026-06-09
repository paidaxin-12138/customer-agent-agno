# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""QMessageBox 深色主题 — macOS 原生弹窗不完全继承全局 QSS 时的补丁。"""
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox

from ui import apple_ui_tokens as T

_MESSAGE_BOX_QSS = f"""
QMessageBox {{
    background-color: {T.BG_TERTIARY};
    color: {T.TEXT_PRIMARY};
}}
QMessageBox QLabel {{
    color: {T.TEXT_PRIMARY};
    background-color: transparent;
}}
QMessageBox QPushButton {{
    background-color: {T.BG_ELEVATED};
    color: {T.TEXT_PRIMARY};
    border: 1px solid {T.BORDER};
    border-radius: {T.RADIUS_SM};
    padding: 8px 18px;
    min-width: 72px;
    min-height: 32px;
}}
QMessageBox QPushButton:hover {{
    background-color: {T.BG_HOVER};
    border-color: {T.BORDER_PANEL};
}}
QMessageBox QPushButton:default {{
    background-color: {T.ACCENT_SURFACE};
    color: {T.ACCENT};
    border: 1px solid {T.ACCENT_SURFACE_BORDER};
}}
"""


def apply_message_box_theme(box: QMessageBox) -> QMessageBox:
    existing = box.styleSheet() or ""
    if "QMessageBox" not in existing:
        box.setStyleSheet(existing + _MESSAGE_BOX_QSS)
    return box


def _themed_static(
    icon: QMessageBox.Icon,
    parent,
    title: str,
    text: str,
    buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
    defaultButton: QMessageBox.StandardButton = QMessageBox.StandardButton.NoButton,
) -> QMessageBox.StandardButton:
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(buttons)
    if defaultButton != QMessageBox.StandardButton.NoButton:
        box.setDefaultButton(defaultButton)
    apply_message_box_theme(box)
    return QMessageBox.StandardButton(box.exec())


def install_themed_message_boxes() -> None:
    """拦截 QMessageBox 静态便捷方法，统一深色可读样式。"""
    mapping = {
        "information": QMessageBox.Icon.Information,
        "warning": QMessageBox.Icon.Warning,
        "critical": QMessageBox.Icon.Critical,
        "question": QMessageBox.Icon.Question,
    }
    for name, icon in mapping.items():
        setattr(
            QMessageBox,
            name,
            staticmethod(
                lambda parent, title, text, buttons=QMessageBox.StandardButton.Ok, defaultButton=QMessageBox.StandardButton.NoButton, ic=icon: _themed_static(  # noqa: E501
                    ic, parent, title, text, buttons, defaultButton
                )
            ),
        )
