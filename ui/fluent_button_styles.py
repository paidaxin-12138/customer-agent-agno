# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""qfluentwidgets PushButton 带图标时的全局样式补丁（避免图标与文字叠层）。"""

from __future__ import annotations

# qfluentwidgets 在 paintEvent 自绘图标（约 x=12），需为文字预留左侧空间
ICON_BUTTON_PADDING = "padding-left: 34px; padding-right: 10px;"


def fluent_icon_button_qss() -> str:
    """追加到应用级 QSS，作用于所有带 hasIcon 属性的 Fluent 按钮。"""
    return f"""
PushButton[hasIcon="true"],
PrimaryPushButton[hasIcon="true"],
TransparentPushButton[hasIcon="true"] {{
    {ICON_BUTTON_PADDING}
}}
"""
