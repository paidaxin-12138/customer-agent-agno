"""UI dialogs helpers for consistent confirmation UX."""

from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QWidget


def confirm_action(
    parent: QWidget,
    title: str,
    content: str,
    *,
    confirm_text: str = "确定",
    cancel_text: str = "取消",
    destructive: bool = False,
) -> bool:
    """Show a localized confirm dialog and return True when confirmed."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning if destructive else QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(content)

    confirm_btn = box.addButton(confirm_text, QMessageBox.ButtonRole.AcceptRole)
    box.addButton(cancel_text, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(confirm_btn)
    box.exec()

    return box.clickedButton() is confirm_btn
