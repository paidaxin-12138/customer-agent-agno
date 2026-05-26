"""
Apple 深色 UI 常量（与「Qt Apple Style UI Design Skill」一致）

原则：大方、简洁、自然；主背景柔和，次级面略提亮，系统蓝作强调，细边框分隔。
"""

# 字体（与规范一致，跨平台降级）
FONT_FAMILY_CSS = (
    '"SF Pro Text", "PingFang SC", "Helvetica Neue", "Segoe UI", '
    '"Roboto", "Microsoft YaHei", sans-serif'
)

# 背景层级
BG_PRIMARY = "#1C1C1E"  # 主窗口
BG_SECONDARY = "#2C2C2E"  # 卡片 / 侧栏 / 分组
BG_TERTIARY = "#3A3A3C"  # hover / 选中底

# 文本
TEXT_PRIMARY = "#FFFFFF"
TEXT_SECONDARY = "#98989D"
TEXT_TERTIARY = "#636366"

# 强调与按钮（系统蓝）
ACCENT = "#0A84FF"
ACCENT_HOVER = "#0055CC"
ACCENT_PRESSED = "#004499"

# 边框 / 分隔（极浅）
BORDER = "rgba(84,84,88,0.35)"
BORDER_LIGHT = "rgba(84,84,88,0.22)"

# 状态
SUCCESS = "#32D74B"
ERROR = "#FF453A"
WARNING = "#FFD60A"

# 圆角（8～12px）
RADIUS_SM = "6px"
RADIUS_MD = "8px"
RADIUS_LG = "10px"
RADIUS_XL = "12px"
