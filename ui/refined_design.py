"""
🎨 Customer-Agent 视觉系统（Apple 风格）

设计原则：
- 清晰层级（Strong hierarchy）
- 中性色底 + 系统蓝强调（Neutral + Accent）
- 更大的圆角与舒适留白（Comfortable spacing）
- 统一交互反馈（Consistent interaction states）
"""

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont, QPalette, QColor

from ui import apple_ui_tokens as APT


# ========== 精修色彩系统（与 apple_ui_tokens / Apple 深色规范一致）==========
class RefinedColors:
    """Apple 深色配色 — 与全局 Fluent + dark_apple 统一。"""

    BG_PRIMARY = APT.BG_PRIMARY
    BG_SECONDARY = APT.BG_SECONDARY
    BG_TERTIARY = APT.BG_TERTIARY  # 输入区 / hover 略亮于卡片

    ACCENT_PRIMARY = APT.ACCENT
    ACCENT_SECONDARY = APT.ACCENT_HOVER
    ACCENT_GRADIENT_START = APT.ACCENT
    ACCENT_GRADIENT_END = "#5AC8FA"

    SUCCESS = APT.SUCCESS
    WARNING = APT.WARNING
    ERROR = APT.ERROR
    INFO = APT.ACCENT

    TEXT_PRIMARY = APT.TEXT_PRIMARY
    TEXT_SECONDARY = APT.TEXT_SECONDARY
    TEXT_TERTIARY = APT.TEXT_SECONDARY
    TEXT_MUTED = APT.TEXT_TERTIARY

    BORDER_SUBTLE = APT.BORDER_LIGHT
    BORDER_DEFAULT = APT.BORDER
    BORDER_HOVER = "rgba(84, 84, 88, 0.5)"
    BORDER_FOCUS = APT.ACCENT

    SURFACE_RAISED = APT.BG_SECONDARY
    SURFACE_OVERLAY = APT.BG_TERTIARY
    SURFACE_HOVER = APT.BG_TERTIARY


# ========== 精修字体系统 ==========
class RefinedFonts:
    """字体系统（优先 SF Pro）。"""

    FAMILY_PRIMARY = APT.FONT_FAMILY_CSS
    FAMILY_DISPLAY = '"SF Pro Display", "PingFang SC", "Helvetica Neue", Arial, sans-serif'
    FAMILY_CODE = "SF Mono, 'Fira Code', 'JetBrains Mono', Consolas, monospace"
    
    # 字号 (更精致的层级)
    SIZE_XS = 10
    SIZE_SM = 12
    SIZE_BASE = 13
    SIZE_LG = 14
    SIZE_XL = 16
    SIZE_2XL = 20
    SIZE_3XL = 24
    SIZE_4XL = 30
    SIZE_5XL = 36
    
    # 字重
    WEIGHT_NORMAL = 400
    WEIGHT_MEDIUM = 500
    WEIGHT_SEMIBOLD = 600
    WEIGHT_BOLD = 700
    
    # 行高
    LINE_HEIGHT_TIGHT = 1.25
    LINE_HEIGHT_NORMAL = 1.5
    LINE_HEIGHT_RELAXED = 1.75


# ========== 精修间距系统 ==========
class RefinedSpacing:
    """精修间距系统 - 4px 网格"""
    
    # 间距 (px)
    PX_0 = 0
    PX_1 = 1
    PX_2 = 2
    PX_3 = 3
    PX_4 = 4
    PX_5 = 5
    PX_6 = 6
    PX_8 = 8
    PX_10 = 10
    PX_12 = 12
    PX_16 = 16
    PX_20 = 20
    PX_24 = 24
    PX_32 = 32
    PX_40 = 40
    PX_48 = 48
    PX_64 = 64


# ========== 精修圆角系统 ==========
class RefinedCorners:
    """精修圆角系统 - 更现代的圆角"""
    
    # 圆角 (px)
    NONE = 0
    SM = 4
    MD = 6
    LG = 8
    XL = 10
    XXL = 12
    FULL = 9999


# ========== 精修阴影系统 ==========
class RefinedShadows:
    """精修阴影系统 - 精致阴影"""
    
    # 阴影 (CSS 格式)
    NONE = "none"
    SM = "0 1px 2px 0 rgba(0, 0, 0, 0.3)"
    MD = "0 4px 6px -1px rgba(0, 0, 0, 0.4), 0 2px 4px -1px rgba(0, 0, 0, 0.3)"
    LG = "0 10px 15px -3px rgba(0, 0, 0, 0.5), 0 4px 6px -2px rgba(0, 0, 0, 0.4)"
    XL = "0 20px 25px -5px rgba(0, 0, 0, 0.6), 0 10px 10px -5px rgba(0, 0, 0, 0.5)"
    
    # 光晕效果 (来自 Linear/Stripe)
    GLOW_PRIMARY = "0 0 20px rgba(94, 106, 210, 0.4)"
    GLOW_SUCCESS = "0 0 20px rgba(16, 185, 129, 0.4)"
    GLOW_ERROR = "0 0 20px rgba(239, 68, 68, 0.4)"


# ========== 精修全局样式表 ==========
REFINED_GLOBAL_STYLESHEET = f"""
/* ========================================
   🎨 Customer-Agent 精修设计系统
   Refined Design System v2.0
   Inspired by: Linear, Vercel, Claude, Stripe, Raycast
   ======================================== */

/* ========== 全局基础 ========== */
* {{
    font-family: {RefinedFonts.FAMILY_PRIMARY};
    outline: none;
    selection-background-color: {RefinedColors.ACCENT_PRIMARY};
    selection-color: {RefinedColors.TEXT_PRIMARY};
}}

QWidget {{
    color: {RefinedColors.TEXT_PRIMARY};
    background-color: {RefinedColors.BG_SECONDARY};
    font-size: {RefinedFonts.SIZE_BASE}pt;
    font-weight: {RefinedFonts.WEIGHT_NORMAL};
}}

QMainWindow {{
    background-color: {RefinedColors.BG_PRIMARY};
}}

QDialog {{
    background-color: {RefinedColors.BG_SECONDARY};
    border: 1px solid {RefinedColors.BORDER_DEFAULT};
    border-radius: {RefinedCorners.XXL}px;
}}

/* ========== 文本标签 ========== */
QLabel {{
    color: {RefinedColors.TEXT_PRIMARY};
    background-color: transparent;
    font-size: {RefinedFonts.SIZE_BASE}pt;
    font-weight: {RefinedFonts.WEIGHT_NORMAL};
}}

QLabel[variant="title"] {{
    font-size: {RefinedFonts.SIZE_3XL}pt;
    font-weight: {RefinedFonts.WEIGHT_BOLD};
    letter-spacing: -0.5px;
}}

QLabel[variant="subtitle"] {{
    font-size: {RefinedFonts.SIZE_2XL}pt;
    font-weight: {RefinedFonts.WEIGHT_SEMIBOLD};
    color: {RefinedColors.TEXT_SECONDARY};
}}

QLabel[variant="caption"] {{
    font-size: {RefinedFonts.SIZE_XS}pt;
    color: {RefinedColors.TEXT_TERTIARY};
}}

QLabel[variant="secondary"] {{
    color: {RefinedColors.TEXT_SECONDARY};
}}

QLabel[variant="muted"] {{
    color: {RefinedColors.TEXT_MUTED};
}}

/* ========== 卡片容器 ========== */
QFrame[variant="card"] {{
    background-color: {RefinedColors.BG_TERTIARY};
    border: 1px solid {RefinedColors.BORDER_SUBTLE};
    border-radius: {RefinedCorners.LG}px;
}}

QFrame[variant="card"]:hover {{
    border: 1px solid {RefinedColors.BORDER_DEFAULT};
}}

QFrame[variant="elevated"] {{
    background-color: {RefinedColors.SURFACE_RAISED};
    border: 1px solid {RefinedColors.BORDER_DEFAULT};
    border-radius: {RefinedCorners.LG}px;
}}

QFrame[variant="separator"] {{
    background-color: {RefinedColors.BORDER_SUBTLE};
    max-height: 1px;
}}

/* ========== 输入框 ========== */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {RefinedColors.BG_TERTIARY};
    color: {RefinedColors.TEXT_PRIMARY};
    border: 1px solid {RefinedColors.BORDER_SUBTLE};
    border-radius: {RefinedCorners.XXL}px;
    padding: 10px 14px;
    font-size: {RefinedFonts.SIZE_BASE}pt;
    selection-background-color: {RefinedColors.ACCENT_PRIMARY};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {RefinedColors.BORDER_FOCUS};
}}

QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{
    background-color: {RefinedColors.BG_SECONDARY};
    color: {RefinedColors.TEXT_MUTED};
}}

QLineEdit::placeholder, QTextEdit::placeholder, QPlainTextEdit::placeholder {{
    color: {RefinedColors.TEXT_TERTIARY};
}}

/* ========== 按钮 ========== */
QPushButton {{
    background-color: {RefinedColors.BG_TERTIARY};
    color: {RefinedColors.TEXT_PRIMARY};
    border: 1px solid {RefinedColors.BORDER_DEFAULT};
    border-radius: {RefinedCorners.XXL}px;
    padding: 10px 20px;
    font-size: {RefinedFonts.SIZE_BASE}pt;
    font-weight: {RefinedFonts.WEIGHT_MEDIUM};
    min-height: 38px;
}}

QPushButton:hover {{
    background-color: {RefinedColors.SURFACE_HOVER};
    border: 1px solid {RefinedColors.BORDER_HOVER};
}}

QPushButton:pressed {{
    background-color: {RefinedColors.SURFACE_RAISED};
}}

QPushButton:disabled {{
    background-color: {RefinedColors.BORDER_SUBTLE};
    color: {RefinedColors.TEXT_MUTED};
}}

/* 按钮变体 */
QPushButton[variant="primary"] {{
    background-color: {RefinedColors.ACCENT_PRIMARY};
    border: 1px solid {RefinedColors.ACCENT_PRIMARY};
}}

QPushButton[variant="primary"]:hover {{
    background-color: {RefinedColors.ACCENT_SECONDARY};
    border: 1px solid {RefinedColors.ACCENT_SECONDARY};
}}

QPushButton[variant="secondary"] {{
    background-color: transparent;
    border: 1px solid {RefinedColors.BORDER_DEFAULT};
    color: {RefinedColors.TEXT_PRIMARY};
}}

QPushButton[variant="secondary"]:hover {{
    background-color: {RefinedColors.SURFACE_HOVER};
    border-color: {RefinedColors.BORDER_HOVER};
}}

QPushButton[variant="danger"] {{
    background-color: {RefinedColors.ERROR};
}}

QPushButton[variant="danger"]:hover {{
    background-color: #DC2626;
}}

QPushButton[variant="ghost"] {{
    background-color: transparent;
    border: none;
    color: {RefinedColors.ACCENT_PRIMARY};
}}

QPushButton[variant="ghost"]:hover {{
    background-color: rgba(255, 255, 255, 0.08);
}}

QPushButton[variant="gradient"] {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 {RefinedColors.ACCENT_GRADIENT_START},
        stop:1 {RefinedColors.ACCENT_GRADIENT_END}
    );
}}

/* ========== 工具按钮 ========== */
QToolButton {{
    background-color: {RefinedColors.BG_TERTIARY};
    color: {RefinedColors.TEXT_PRIMARY};
    border: 1px solid {RefinedColors.BORDER_SUBTLE};
    border-radius: {RefinedCorners.XL}px;
    padding: 8px 14px;
    font-size: {RefinedFonts.SIZE_BASE}pt;
}}

QToolButton:hover {{
    background-color: {RefinedColors.SURFACE_HOVER};
    border: 1px solid {RefinedColors.BORDER_HOVER};
}}

QToolButton:pressed {{
    background-color: {RefinedColors.BG_SECONDARY};
}}

QToolButton:checked {{
    background-color: {RefinedColors.ACCENT_PRIMARY};
    border: 1px solid {RefinedColors.ACCENT_PRIMARY};
}}

/* ========== 下拉框 ========== */
QComboBox {{
    background-color: {RefinedColors.BG_TERTIARY};
    color: {RefinedColors.TEXT_PRIMARY};
    border: 1px solid {RefinedColors.BORDER_SUBTLE};
    border-radius: {RefinedCorners.XXL}px;
    padding: 8px 12px;
    min-height: 36px;
}}

QComboBox:hover {{
    border: 1px solid {RefinedColors.BORDER_HOVER};
}}

QComboBox:focus {{
    border: 1px solid {RefinedColors.BORDER_FOCUS};
}}

QComboBox::drop-down {{
    border: none;
    width: 30px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {RefinedColors.TEXT_SECONDARY};
    margin-right: 10px;
}}

QComboBox QAbstractItemView {{
    background-color: {RefinedColors.SURFACE_RAISED};
    color: {RefinedColors.TEXT_PRIMARY};
    border: 1px solid {RefinedColors.BORDER_DEFAULT};
    border-radius: {RefinedCorners.MD}px;
    selection-background-color: {RefinedColors.ACCENT_PRIMARY};
    selection-color: {RefinedColors.TEXT_PRIMARY};
    outline: none;
    padding: 4px;
}}

QComboBox QAbstractItemView::item {{
    min-height: 40px;
    padding: 8px 12px;
    border-radius: {RefinedCorners.SM}px;
}}

QComboBox QAbstractItemView::item:hover {{
    background-color: {RefinedColors.BORDER_SUBTLE};
}}

QComboBox QAbstractItemView::item:selected {{
    background-color: {RefinedColors.ACCENT_PRIMARY};
}}

/* ========== 列表视图 ========== */
QListView, QListWidget {{
    background-color: {RefinedColors.BG_PRIMARY};
    color: {RefinedColors.TEXT_PRIMARY};
    border: none;
    outline: none;
    show-decoration-selected: 1;
}}

QListView::item, QListWidget::item {{
    background-color: transparent;
    padding: 12px 16px;
    border-radius: {RefinedCorners.MD}px;
    margin: 2px 8px;
    min-height: 50px;
}}

QListView::item:hover, QListWidget::item:hover {{
    background-color: {RefinedColors.BG_TERTIARY};
}}

QListView::item:selected, QListWidget::item:selected {{
    background-color: {RefinedColors.ACCENT_PRIMARY};
    color: {RefinedColors.TEXT_PRIMARY};
}}

QListView::item:selected:hover, QListWidget::item:selected:hover {{
    background-color: {RefinedColors.ACCENT_SECONDARY};
}}

/* ========== 树形视图 ========== */
QTreeView, QTreeWidget {{
    background-color: {RefinedColors.BG_PRIMARY};
    color: {RefinedColors.TEXT_PRIMARY};
    border: none;
    outline: none;
    show-decoration-selected: 1;
}}

QTreeView::item, QTreeWidget::item {{
    padding: 8px 12px;
    border-radius: {RefinedCorners.SM}px;
    margin: 2px 4px;
}}

QTreeView::item:hover, QTreeWidget::item:hover {{
    background-color: {RefinedColors.BG_TERTIARY};
}}

QTreeView::item:selected, QTreeWidget::item:selected {{
    background-color: {RefinedColors.ACCENT_PRIMARY};
}}

QTreeView::branch {{
    background-color: transparent;
}}

/* ========== 表格视图 ========== */
QTableView, QTableWidget {{
    background-color: {RefinedColors.BG_PRIMARY};
    color: {RefinedColors.TEXT_PRIMARY};
    border: 1px solid {RefinedColors.BORDER_SUBTLE};
    border-radius: {RefinedCorners.XXL}px;
    gridline-color: {RefinedColors.BORDER_SUBTLE};
    selection-background-color: #24344D;
    selection-color: {RefinedColors.TEXT_PRIMARY};
}}

QTableView::item, QTableWidget::item {{
    padding: 10px 14px;
    border-radius: {RefinedCorners.SM}px;
}}

QTableView::item:selected, QTableWidget::item:selected {{
    background-color: {RefinedColors.ACCENT_PRIMARY};
}}

QHeaderView::section {{
    background-color: {RefinedColors.BG_TERTIARY};
    color: {RefinedColors.TEXT_SECONDARY};
    border: none;
    border-bottom: 1px solid {RefinedColors.BORDER_SUBTLE};
    border-right: 1px solid {RefinedColors.BORDER_SUBTLE};
    padding: 12px 16px;
    font-weight: {RefinedFonts.WEIGHT_MEDIUM};
    font-size: {RefinedFonts.SIZE_SM}pt;
}}

QHeaderView::section:first {{
    border-top-left-radius: {RefinedCorners.LG}px;
}}

QHeaderView::section:last {{
    border-top-right-radius: {RefinedCorners.LG}px;
    border-right: none;
}}

/* ========== 标签页 ========== */
QTabWidget::pane {{
    background-color: {RefinedColors.BG_PRIMARY};
    border: 1px solid {RefinedColors.BORDER_SUBTLE};
    border-radius: {RefinedCorners.LG}px;
    padding: 16px;
}}

QTabBar::tab {{
    background-color: transparent;
    color: {RefinedColors.TEXT_SECONDARY};
    border: none;
    padding: 10px 20px;
    margin-right: 4px;
    font-size: {RefinedFonts.SIZE_BASE}pt;
    font-weight: {RefinedFonts.WEIGHT_MEDIUM};
    border-bottom: 2px solid transparent;
}}

QTabBar::tab:hover {{
    color: {RefinedColors.TEXT_PRIMARY};
    background-color: {RefinedColors.BG_TERTIARY};
    border-radius: {RefinedCorners.SM}px;
}}

QTabBar::tab:selected {{
    color: {RefinedColors.ACCENT_PRIMARY};
    border-bottom: 2px solid {RefinedColors.ACCENT_PRIMARY};
}}

QTabBar::tab:first:selected {{
    border-top-left-radius: {RefinedCorners.MD}px;
}}

QTabBar::tab:last:selected {{
    border-top-right-radius: {RefinedCorners.MD}px;
}}

/* ========== 滚动条 ========== */
QScrollBar:vertical {{
    background-color: transparent;
    width: 8px;
    border-radius: 4px;
    margin: 4px;
}}

QScrollBar::handle:vertical {{
    background-color: {RefinedColors.BORDER_DEFAULT};
    border-radius: 4px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {RefinedColors.BORDER_HOVER};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background-color: transparent;
    height: 8px;
    border-radius: 4px;
    margin: 4px;
}}

QScrollBar::handle:horizontal {{
    background-color: {RefinedColors.BORDER_DEFAULT};
    border-radius: 4px;
    min-width: 30px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {RefinedColors.BORDER_HOVER};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ========== 进度条 ========== */
QProgressBar {{
    background-color: {RefinedColors.BG_TERTIARY};
    border-radius: {RefinedCorners.FULL}px;
    text-align: center;
    color: {RefinedColors.TEXT_PRIMARY};
    font-size: {RefinedFonts.SIZE_XS}pt;
    font-weight: {RefinedFonts.WEIGHT_MEDIUM};
    height: 6px;
    border: none;
}}

QProgressBar::chunk {{
    background-color: {RefinedColors.ACCENT_PRIMARY};
    border-radius: {RefinedCorners.FULL}px;
}}

/* ========== 分组框 ========== */
QGroupBox {{
    background-color: {RefinedColors.BG_TERTIARY};
    border: 1px solid {RefinedColors.BORDER_SUBTLE};
    border-radius: {RefinedCorners.LG}px;
    margin-top: 20px;
    padding-top: 20px;
    font-size: {RefinedFonts.SIZE_LG}pt;
    font-weight: {RefinedFonts.WEIGHT_SEMIBOLD};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 16px;
    top: -10px;
    padding: 0 8px;
    color: {RefinedColors.TEXT_SECONDARY};
    background-color: {RefinedColors.BG_TERTIARY};
}}

/* ========== 复选框 ========== */
QCheckBox {{
    color: {RefinedColors.TEXT_PRIMARY};
    spacing: 10px;
    font-size: {RefinedFonts.SIZE_BASE}pt;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 6px;
    border: 1px solid {RefinedColors.BORDER_DEFAULT};
    background-color: {RefinedColors.BG_TERTIARY};
}}

QCheckBox::indicator:hover {{
    border: 1px solid {RefinedColors.ACCENT_PRIMARY};
}}

QCheckBox::indicator:checked {{
    background-color: {RefinedColors.ACCENT_PRIMARY};
    border: 1px solid {RefinedColors.ACCENT_PRIMARY};
}}

/* ========== 单选按钮 ========== */
QRadioButton {{
    color: {RefinedColors.TEXT_PRIMARY};
    spacing: 10px;
    font-size: {RefinedFonts.SIZE_BASE}pt;
}}

QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 1px solid {RefinedColors.BORDER_DEFAULT};
    background-color: {RefinedColors.BG_TERTIARY};
}}

QRadioButton::indicator:hover {{
    border: 1px solid {RefinedColors.ACCENT_PRIMARY};
}}

QRadioButton::indicator:checked {{
    background-color: {RefinedColors.ACCENT_PRIMARY};
    border: 1px solid {RefinedColors.ACCENT_PRIMARY};
}}

/* ========== 滑块 ========== */
QSlider::groove:horizontal {{
    background-color: {RefinedColors.BG_TERTIARY};
    height: 4px;
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background-color: {RefinedColors.TEXT_PRIMARY};
    width: 18px;
    height: 18px;
    margin: -7px 0;
    border-radius: 9px;
}}

QSlider::handle:horizontal:hover {{
    background-color: {RefinedColors.ACCENT_PRIMARY};
}}

QSlider::sub-page:horizontal {{
    background-color: {RefinedColors.ACCENT_PRIMARY};
    border-radius: 2px;
}}

/* ========== 工具提示 ========== */
QToolTip {{
    background-color: {RefinedColors.SURFACE_RAISED};
    color: {RefinedColors.TEXT_PRIMARY};
    border: 1px solid {RefinedColors.BORDER_DEFAULT};
    border-radius: {RefinedCorners.MD}px;
    padding: 8px 12px;
    font-size: {RefinedFonts.SIZE_XS}pt;
}}

/* ========== 菜单 ========== */
QMenu {{
    background-color: {RefinedColors.SURFACE_RAISED};
    color: {RefinedColors.TEXT_PRIMARY};
    border: 1px solid {RefinedColors.BORDER_DEFAULT};
    border-radius: {RefinedCorners.LG}px;
    padding: 8px;
}}

QMenu::item {{
    padding: 10px 16px;
    border-radius: {RefinedCorners.MD}px;
    margin: 2px 4px;
}}

QMenu::item:selected {{
    background-color: {RefinedColors.ACCENT_PRIMARY};
}}

QMenu::separator {{
    height: 1px;
    background-color: {RefinedColors.BORDER_SUBTLE};
    margin: 6px 8px;
}}

/* ========== 状态指示器 ========== */
QLabel[status="online"] {{
    color: {RefinedColors.SUCCESS};
}}

QLabel[status="offline"] {{
    color: {RefinedColors.TEXT_MUTED};
}}

QLabel[status="busy"] {{
    color: {RefinedColors.WARNING};
}}

QLabel[status="error"] {{
    color: {RefinedColors.ERROR};
}}

/* ========== 徽章 ========== */
QLabel[variant="badge"] {{
    background-color: {RefinedColors.ERROR};
    color: {RefinedColors.TEXT_PRIMARY};
    border-radius: {RefinedCorners.FULL}px;
    padding: 2px 8px;
    font-size: {RefinedFonts.SIZE_XS}pt;
    font-weight: {RefinedFonts.WEIGHT_SEMIBOLD};
    min-width: 20px;
}}

QLabel[variant="badge"][type="success"] {{
    background-color: {RefinedColors.SUCCESS};
}}

QLabel[variant="badge"][type="warning"] {{
    background-color: {RefinedColors.WARNING};
}}

QLabel[variant="badge"][type="info"] {{
    background-color: {RefinedColors.INFO};
}}

/* ========== 分割线 ========== */
Line, QFrame[frameShape="4"] {{
    background-color: {RefinedColors.BORDER_SUBTLE};
    max-height: 1px;
}}

QFrame[frameShape="5"] {{
    background-color: {RefinedColors.BORDER_SUBTLE};
    max-width: 1px;
}}

/* ========== 特殊组件 ========== */

/* 导航栏 */
QFrame[variant="navigation"] {{
    background-color: {RefinedColors.BG_PRIMARY};
    border-right: 1px solid {RefinedColors.BORDER_SUBTLE};
}}

/* 侧边栏 */
QFrame[variant="sidebar"] {{
    background-color: {RefinedColors.BG_PRIMARY};
    border-right: 1px solid {RefinedColors.BORDER_SUBTLE};
}}

/* 顶部栏 */
QFrame[variant="header"] {{
    background-color: {RefinedColors.BG_PRIMARY};
    border-bottom: 1px solid {RefinedColors.BORDER_SUBTLE};
}}

/* 底部栏 */
QFrame[variant="footer"] {{
    background-color: {RefinedColors.BG_PRIMARY};
    border-top: 1px solid {RefinedColors.BORDER_SUBTLE};
}}

/* 内容区域 */
QFrame[variant="content"] {{
    background-color: {RefinedColors.BG_PRIMARY};
}}

/* 英雄区域 (Hero Section) */
QFrame[variant="hero"] {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 {RefinedColors.BG_TERTIARY},
        stop:1 {RefinedColors.BG_SECONDARY}
    );
    border: 1px solid {RefinedColors.BORDER_SUBTLE};
    border-radius: {RefinedCorners.XL}px;
    padding: 40px;
}}

/* 统计卡片 */
QFrame[variant="stat-card"] {{
    background-color: {RefinedColors.BG_TERTIARY};
    border: 1px solid {RefinedColors.BORDER_SUBTLE};
    border-radius: {RefinedCorners.LG}px;
    padding: 20px;
}}

/* 渐变按钮 */
QPushButton[variant="gradient"] {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 {RefinedColors.ACCENT_GRADIENT_START},
        stop:1 {RefinedColors.ACCENT_GRADIENT_END}
    );
    border: none;
}}

/* ========== 动画效果 ========== */
/* 注意：PyQt6 QSS 不支持过渡动画，但可以通过代码实现 */

/* ========== 辅助类 ========== */
QWidget[accessible="true"] {{
    outline: 2px solid {RefinedColors.ACCENT_PRIMARY};
    outline-offset: 2px;
}}

QWidget[hidden="true"] {{
    visibility: hidden;
}}

QWidget[disabled="true"] {{
    opacity: 0.5;
}}
"""


# ========== 应用函数 ==========
def apply_refined_design(app: QApplication) -> None:
    """
    应用精修设计系统到整个应用
    
    Args:
        app: QApplication 实例
    """
    app.setStyleSheet(REFINED_GLOBAL_STYLESHEET)

    font = QFont()
    font.setFamilies(
        [
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
    
    # 设置调色板
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(RefinedColors.BG_SECONDARY))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(RefinedColors.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Base, QColor(RefinedColors.BG_TERTIARY))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(RefinedColors.BG_SECONDARY))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(RefinedColors.SURFACE_RAISED))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(RefinedColors.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Text, QColor(RefinedColors.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Button, QColor(RefinedColors.BG_TERTIARY))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(RefinedColors.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(RefinedColors.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Link, QColor(RefinedColors.ACCENT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(RefinedColors.ACCENT_PRIMARY))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(RefinedColors.TEXT_PRIMARY))
    app.setPalette(palette)


def get_color(color_name: str) -> str:
    """获取精修设计系统颜色"""
    return getattr(RefinedColors, color_name.upper(), RefinedColors.TEXT_PRIMARY)


def get_font_size(size_name: str) -> int:
    """获取精修设计系统字号"""
    return getattr(RefinedFonts, f"SIZE_{size_name.upper()}", RefinedFonts.SIZE_BASE)


def get_spacing(spacing_name: str) -> int:
    """获取精修设计系统间距"""
    return getattr(RefinedSpacing, f"PX_{spacing_name.upper()}", RefinedSpacing.PX_12)


def get_corner(corner_name: str) -> int:
    """获取精修设计系统圆角"""
    return getattr(RefinedCorners, corner_name.upper(), RefinedCorners.MD)
