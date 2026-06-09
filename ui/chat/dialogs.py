# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""实时聊天对话框。"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import ScrollArea

from ui import apple_ui_tokens as UI


def avatar_letter(name: str, fallback: str = "?") -> str:
    s = (name or "").strip()
    if not s:
        return fallback
    return s[0].upper() if s.isascii() and len(s) == 1 else s[0]


class GoodsIdInputDialog(QDialog):
    """商品 ID 输入（12 位，禁止粘贴）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("发送商品卡")
        self.setFixedSize(400, 200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)

        info_label = QLabel("请输入商品 ID（goods_id）\n支持 12 位数字，禁止粘贴")
        info_label.setStyleSheet("color: #8E8E93; font-size: 13px;")
        layout.addWidget(info_label)

        self.input = QLineEdit()
        self.input.setPlaceholderText("请输入 12 位商品 ID")
        self.input.setMaxLength(12)
        self.input.setStyleSheet(
            """
            QLineEdit {
                padding: 10px;
                font-size: 16px;
                border: 2px solid #007AFF;
                border-radius: 8px;
            }
            QLineEdit:focus {
                border: 2px solid #0055CC;
            }
        """
        )
        self.input.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        layout.addWidget(self.input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_goods_id(self) -> int:
        try:
            return int(self.input.text().strip())
        except (ValueError, TypeError):
            return 0


class EmojiPickerDialog(QDialog):
    """表情选择器（深色）。"""

    _DIALOG_STYLE = f"""
        QDialog {{
            background-color: {UI.BG_PRIMARY};
        }}
        QLabel {{
            color: {UI.TEXT_SECONDARY};
            background: transparent;
        }}
        QScrollArea {{
            background-color: {UI.BG_SECONDARY};
            border: 1px solid {UI.BORDER};
            border-radius: 10px;
        }}
        QWidget#EmojiPickerGrid {{
            background-color: {UI.BG_SECONDARY};
        }}
    """

    _EMOJI_BTN_STYLE = f"""
        QPushButton {{
            font-size: 28px;
            background-color: transparent;
            border: 2px solid transparent;
            border-radius: 8px;
        }}
        QPushButton:hover {{
            background-color: {UI.BG_TERTIARY};
            border: 2px solid {UI.ACCENT};
        }}
        QPushButton:pressed {{
            background-color: {UI.ACCENT_PRESSED};
        }}
    """

    _FAV_BTN_STYLE = f"""
        QPushButton {{
            font-size: 24px;
            background-color: transparent;
            border: none;
            border-radius: 6px;
        }}
        QPushButton:hover {{
            background-color: {UI.BG_TERTIARY};
        }}
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_emoji = None
        self.setWindowTitle("选择表情")
        self.setFixedSize(520, 420)
        self.setStyleSheet(self._DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        emoji_widget = QWidget()
        emoji_widget.setObjectName("EmojiPickerGrid")
        emoji_layout = QGridLayout(emoji_widget)
        emoji_layout.setContentsMargins(10, 10, 10, 10)
        emoji_layout.setSpacing(8)

        raw_emojis = [
            "😊", "😂", "😍", "", "😘", "😜", "😝", "😛",
            "😅", "😆", "😁", "🙂", "🙃", "😉", "😌", "",
            "😒", "😞", "😔", "😟", "😕", "🙁", "☹️", "😣",
            "😖", "😫", "😩", "😤", "😠", "😡", "😶", "😐",
            "😑", "😬", "🙄", "😯", "😦", "😧", "😨", "😰",
            "😥", "😓", "🤗", "🤔", "🤐", "🤓", "", "😝",
            "🤑", "🤒", "🤕", "😷", "🤢", "", "🤧", "😇",
            "🤠", "🤡", "", "🤫", "🤭", "🧐", "", "😈",
            "👍", "👎", "👌", "✌️", "🤞", "🤟", "🤘", "👋",
            "👏", "", "💪", "🤝", "❤️", "💔", "💕", "💖",
            "🎉", "✨", "🔥", "🌟", "💯", "💐", "🌹", "🎁",
        ]
        emojis = [e for e in raw_emojis if e]

        row = col = 0
        for emoji in emojis:
            btn = QPushButton(emoji)
            btn.setFixedSize(44, 44)
            btn.setStyleSheet(self._EMOJI_BTN_STYLE)
            btn.clicked.connect(lambda checked, e=emoji: self._on_emoji_selected(e))
            emoji_layout.addWidget(btn, row, col)
            col += 1
            if col >= 8:
                col = 0
                row += 1

        scroll.setWidget(emoji_widget)
        layout.addWidget(scroll)

        favorites_layout = QHBoxLayout()
        favorites_layout.setSpacing(8)
        fav_label = QLabel("常用")
        fav_label.setStyleSheet(f"font-size: 12px; color: {UI.TEXT_SECONDARY};")
        favorites_layout.addWidget(fav_label)
        for fav in ["😊", "😂", "❤️", "👍", "🎉", "🔥"]:
            btn = QPushButton(fav)
            btn.setFixedSize(36, 36)
            btn.setStyleSheet(self._FAV_BTN_STYLE)
            btn.clicked.connect(lambda checked, e=fav: self._on_emoji_selected(e))
            favorites_layout.addWidget(btn)
        favorites_layout.addStretch()
        layout.addLayout(favorites_layout)

    def _on_emoji_selected(self, emoji: str) -> None:
        self.selected_emoji = emoji
        self.accept()

    def exec(self) -> str:
        self.selected_emoji = None
        super().exec()
        return self.selected_emoji
