# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
统一深色 SaaS UI 色板（现代后台看板）

全应用唯一色板；dark_theme.qss / theme.py / 各页面均引用此处。
"""

# 字体（Inter 优先，跨平台降级）
FONT_FAMILY_CSS = (
    '"Inter", "SF Pro Text", "PingFang SC", "Helvetica Neue", "Segoe UI", '
    '"Roboto", "Microsoft YaHei", sans-serif'
)

# 背景层级
BG_PRIMARY = "#131315"
BG_SECONDARY = "#1b1b1d"
BG_TERTIARY = "#1f1f21"
BG_ELEVATED = "#2a2a2c"
BG_HOVER = "#353437"

# 玻璃面板（与卡片统一为同一层级色，避免多层色块）
GLASS_PANEL = "#1f1f21"
GLASS_PANEL_SOLID = BG_TERTIARY

# 文字
TEXT_PRIMARY = "#e4e2e4"
TEXT_SECONDARY = "#c0c6d6"
TEXT_TERTIARY = "#98989d"
TEXT_MUTED = "rgba(255, 255, 255, 0.5)"
TEXT_PLACEHOLDER = "rgba(255, 255, 255, 0.5)"

# 强调色（小面积：文字、链接、Tab 下划线）
ACCENT = "#9bb8f0"
ACCENT_SECONDARY = "#b0aff0"
ACCENT_HOVER = "#aac7ff"
ACCENT_PRESSED = "#7a9ee6"

# 强调色（大面积：气泡、按钮底 — 避免 #aac7ff 整块刺眼）
ACCENT_SURFACE = "rgba(155, 184, 240, 0.14)"
ACCENT_SURFACE_HOVER = "rgba(155, 184, 240, 0.22)"
ACCENT_SURFACE_BORDER = "rgba(155, 184, 240, 0.32)"
ACCENT_FILL = "#3d4f66"
ACCENT_FILL_HOVER = "#4a5d78"

# 状态
SUCCESS = "#47e266"
ERROR = "#ffb4ab"
WARNING = "#ffd60a"
INFO = ACCENT

# 边框
BORDER = "rgba(255, 255, 255, 0.08)"
BORDER_LIGHT = "rgba(255, 255, 255, 0.05)"
BORDER_PANEL = "rgba(255, 255, 255, 0.1)"
BORDER_FOCUS = ACCENT
GRID_LINE = "rgba(255, 255, 255, 0.05)"

# 圆角
RADIUS_SM = "8px"
RADIUS_MD = "16px"
RADIUS_LG = "24px"
RADIUS_PILL = "9999px"

# 布局
NAV_WIDTH = 280
TOP_BAR_HEIGHT = 64
