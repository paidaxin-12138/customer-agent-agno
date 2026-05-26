"""
干净简洁的 UI 设计系统
Clean & Minimalist Design System for Customer-Agent
"""

from PyQt6.QtGui import QFont, QColor, QIcon
from PyQt6.QtCore import Qt
from qfluentwidgets import setTheme, Theme
from utils.logger_loguru import get_logger

logger = get_logger("CleanDesign")

# ============ 颜色方案 ============

class CleanColors:
    """干净配色方案"""
    
    # 主色调 - 使用清新的蓝色
    PRIMARY = "#0066CC"           # 主蓝色
    PRIMARY_LIGHT = "#3399FF"     # 浅蓝色
    PRIMARY_DARK = "#004C99"      # 深蓝色
    
    # 背景色
    BACKGROUND = "#FFFFFF"        # 纯白背景
    SECONDARY_BG = "#F5F7FA"      # 浅灰背景
    CARD_BG = "#FFFFFF"           # 卡片背景
    
    # 文字颜色
    TEXT_PRIMARY = "#1A1A1A"      # 主文字
    TEXT_SECONDARY = "#666666"    # 次要文字
    TEXT_PLACEHOLDER = "#999999"  # 占位文字
    
    # 边框
    BORDER = "#E0E0E0"            # 边框颜色
    BORDER_LIGHT = "#F0F0F0"      # 浅边框
    
    # 状态色
    SUCCESS = "#52C41A"           # 成功绿
    WARNING = "#FAAD14"           # 警告黄
    ERROR = "#F5222D"             # 错误红
    INFO = "#1890FF"              # 信息蓝


# ============ 字体方案 ============

class CleanFonts:
    """干净字体方案"""
    
    # 字体家族
    FONT_FAMILY = "Microsoft YaHei"  # 微软雅黑
    
    # 字体大小
    FONT_TINY = 9
    FONT_SMALL = 11
    FONT_NORMAL = 12
    FONT_MEDIUM = 14
    FONT_LARGE = 16
    FONT_XLARGE = 18
    FONT_XXLARGE = 24
    
    @staticmethod
    def get_font(size=FONT_NORMAL, bold=False):
        """获取字体"""
        weight = QFont.Weight.Bold if bold else QFont.Weight.Normal
        font = QFont(CleanFonts.FONT_FAMILY, size)
        font.setWeight(weight)
        return font


# ============ 间距方案 ============

class CleanSpacing:
    """干净间距方案"""
    
    SPACING_XS = 4    # 超小间距
    SPACING_S = 8     # 小间距
    SPACING_M = 12    # 中间距
    SPACING_L = 16    # 大间距
    SPACING_XL = 24   # 超大间距
    SPACING_XXL = 32  # 特大间距


# ============ 圆角方案 ============

class CleanRadius:
    """干净圆角方案"""
    
    RADIUS_NONE = 0
    RADIUS_S = 4
    RADIUS_M = 8
    RADIUS_L = 12
    RADIUS_XL = 16


# ============ 应用设计系统 ============

def apply_clean_design(app):
    """
    应用干净设计系统
    
    Args:
        app: QApplication 实例
    """
    logger.info("应用干净设计系统...")
    
    # 设置浅色主题
    setTheme(Theme.LIGHT)
    
    # 设置全局样式
    apply_global_styles(app)
    
    logger.info("干净设计系统应用完成")


def apply_global_styles(app):
    """应用全局样式"""
    
    # 全局样式表
    stylesheet = """
/* ============ 全局样式 ============ */

/* 主窗口 */
QMainWindow {
    background-color: #FFFFFF;
    font-family: "Microsoft YaHei";
    font-size: 12px;
    color: #1A1A1A;
}

/* ============ 按钮样式 ============ */

/* 主按钮 */
QPushButton#primaryButton,
QPushButton[fluent-type="primary"] {
    background-color: #0066CC;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 8px 20px;
    font-size: 13px;
    font-weight: bold;
}

QPushButton#primaryButton:hover,
QPushButton[fluent-type="primary"]:hover {
    background-color: #3399FF;
}

QPushButton#primaryButton:pressed,
QPushButton[fluent-type="primary"]:pressed {
    background-color: #004C99;
}

/* 普通按钮 */
QPushButton {
    background-color: white;
    color: #1A1A1A;
    border: 1px solid #E0E0E0;
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 12px;
}

QPushButton:hover {
    background-color: #F5F7FA;
    border-color: #0066CC;
}

QPushButton:pressed {
    background-color: #E8EDF2;
}

/* 禁用按钮 */
QPushButton:disabled {
    background-color: #F5F5F5;
    color: #CCCCCC;
    border-color: #E0E0E0;
}

/* ============ 输入框样式 ============ */

QLineEdit,
QTextEdit,
QPlainTextEdit {
    background-color: white;
    border: 1px solid #E0E0E0;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 12px;
    color: #1A1A1A;
    selection-background-color: #0066CC;
}

QLineEdit:focus,
QTextEdit:focus,
QPlainTextEdit:focus {
    border-color: #0066CC;
    border-width: 2px;
    padding: 7px 11px;
}

QLineEdit:disabled,
QTextEdit:disabled {
    background-color: #F5F5F5;
    color: #999999;
}

QLineEdit::placeholder {
    color: #999999;
}

/* ============ 标签样式 ============ */

QLabel {
    color: #1A1A1A;
    font-size: 12px;
    background: transparent;
}

QLabel#titleLabel {
    font-size: 16px;
    font-weight: bold;
    color: #1A1A1A;
}

QLabel#subtitleLabel {
    font-size: 13px;
    color: #666666;
}

QLabel#sectionTitle {
    font-size: 14px;
    font-weight: bold;
    color: #1A1A1A;
    padding: 8px 0;
}

/* ============ 卡片容器 ============ */

QFrame#cardFrame,
QFrame[fluent-type="card"] {
    background-color: white;
    border: 1px solid #E0E0E0;
    border-radius: 8px;
    padding: 12px;
}

QFrame#cardFrame:hover {
    border-color: #0066CC;
    background-color: #FAFBFC;
}

/* ============ 列表样式 ============ */

QListView,
QListWidget {
    background-color: white;
    border: 1px solid #E0E0E0;
    border-radius: 6px;
    outline: none;
}

QListView::item,
QListWidget::item {
    padding: 8px 12px;
    border-bottom: 1px solid #F0F0F0;
}

QListView::item:hover,
QListWidget::item:hover {
    background-color: #F5F7FA;
}

QListView::item:selected,
QListWidget::item:selected {
    background-color: #E6F0FF;
    color: #0066CC;
    border-left: 3px solid #0066CC;
}

/* ============ 表格样式 ============ */

QTableView,
QTableWidget {
    background-color: white;
    alternate-background-color: #FAFBFC;
    border: 1px solid #E0E0E0;
    border-radius: 6px;
    gridline-color: #F0F0F0;
    selection-background-color: #E6F0FF;
    selection-color: #0066CC;
}

QTableView::item,
QTableWidget::item {
    padding: 6px 8px;
}

QHeaderView::section {
    background-color: #F5F7FA;
    color: #666666;
    font-weight: bold;
    padding: 8px;
    border: none;
    border-bottom: 2px solid #E0E0E0;
}

/* ============ 滚动条样式 ============ */

QScrollBar:vertical {
    background-color: #F5F5F5;
    width: 8px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background-color: #CCCCCC;
    border-radius: 4px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background-color: #999999;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: #F5F5F5;
    height: 8px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal {
    background-color: #CCCCCC;
    border-radius: 4px;
    min-width: 20px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #999999;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ============ 组合框样式 ============ */

QComboBox {
    background-color: white;
    border: 1px solid #E0E0E0;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
}

QComboBox:hover {
    border-color: #0066CC;
}

QComboBox:focus {
    border-color: #0066CC;
    border-width: 2px;
    padding: 5px 11px;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: white;
    border: 1px solid #E0E0E0;
    border-radius: 6px;
    selection-background-color: #E6F0FF;
}

/* ============ 分组框样式 ============ */

QGroupBox {
    background-color: white;
    border: 1px solid #E0E0E0;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 12px;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 8px;
    color: #1A1A1A;
}

/* ============ 标签页样式 ============ */

QTabWidget::pane {
    background-color: white;
    border: 1px solid #E0E0E0;
    border-radius: 6px;
    top: -1px;
}

QTabBar::tab {
    background-color: white;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    padding: 8px 16px;
    color: #666666;
}

QTabBar::tab:hover {
    color: #0066CC;
}

QTabBar::tab:selected {
    color: #0066CC;
    border-bottom-color: #0066CC;
    font-weight: bold;
}

/* ============ 进度条样式 ============ */

QProgressBar {
    background-color: #F0F0F0;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}

QProgressBar::chunk {
    background-color: #0066CC;
    border-radius: 4px;
}

/* ============ 复选框样式 ============ */

QCheckBox {
    color: #1A1A1A;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #E0E0E0;
    border-radius: 4px;
    background-color: white;
}

QCheckBox::indicator:checked {
    background-color: #0066CC;
    border-color: #0066CC;
}

QCheckBox::indicator:hover {
    border-color: #0066CC;
}

/* ============ 单选框样式 ============ */

QRadioButton {
    color: #1A1A1A;
    spacing: 8px;
}

QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #E0E0E0;
    border-radius: 8px;
    background-color: white;
}

QRadioButton::indicator:checked {
    background-color: #0066CC;
    border-color: #0066CC;
}

QRadioButton::indicator:hover {
    border-color: #0066CC;
}

/* ============ 工具提示样式 ============ */

QToolTip {
    background-color: #1A1A1A;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 11px;
}

/* ============ 菜单样式 ============ */

QMenu {
    background-color: white;
    border: 1px solid #E0E0E0;
    border-radius: 6px;
    padding: 8px 0;
}

QMenu::item {
    padding: 8px 20px;
    color: #1A1A1A;
}

QMenu::item:selected {
    background-color: #F5F7FA;
}

QMenu::separator {
    height: 1px;
    background-color: #E0E0E0;
    margin: 4px 0;
}

/* ============ 状态指示器 ============ */

QLabel#statusOnline {
    color: #52C41A;
    font-weight: bold;
}

QLabel#statusOffline {
    color: #999999;
    font-weight: bold;
}

QLabel#statusBusy {
    color: #FAAD14;
    font-weight: bold;
}

/* ============ 消息气泡 ============ */

QFrame#messageBubble {
    background-color: #F5F7FA;
    border-radius: 8px;
    padding: 12px;
}

QFrame#messageBubble[user="self"] {
    background-color: #E6F0FF;
}

QFrame#messageBubble[user="other"] {
    background-color: #F5F7FA;
}

/* ============ 分隔线 ============ */

QFrame#line {
    background-color: #E0E0E0;
    max-height: 1px;
}

QFrame[fluent-type="separator"] {
    background-color: #F0F0F0;
    max-height: 1px;
}

    """
    
    app.setStyleSheet(stylesheet)
    logger.info("全局样式应用完成")


# ============ 便捷函数 ============

def create_card(parent, layout_type="vertical", spacing=12):
    """创建卡片容器"""
    from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout
    
    card = QFrame(parent)
    card.setObjectName("cardFrame")
    
    if layout_type == "vertical":
        layout = QVBoxLayout(card)
        layout.setSpacing(spacing)
    else:
        layout = QHBoxLayout(card)
        layout.setSpacing(spacing)
    
    layout.setContentsMargins(12, 12, 12, 12)
    return card, layout


def create_label(text, parent, type="normal"):
    """创建标签"""
    from PyQt6.QtWidgets import QLabel
    
    label = QLabel(text, parent)
    
    if type == "title":
        label.setObjectName("titleLabel")
        label.setFont(CleanFonts.get_font(CleanFonts.FONT_LARGE, bold=True))
    elif type == "subtitle":
        label.setObjectName("subtitleLabel")
        label.setFont(CleanFonts.get_font(CleanFonts.FONT_SMALL))
    elif type == "section":
        label.setObjectName("sectionTitle")
        label.setFont(CleanFonts.get_font(CleanFonts.FONT_MEDIUM, bold=True))
    else:
        label.setFont(CleanFonts.get_font(CleanFonts.FONT_NORMAL))
    
    return label


def create_button(text, parent, type="normal"):
    """创建按钮"""
    from PyQt6.QtWidgets import QPushButton
    
    button = QPushButton(text, parent)
    
    if type == "primary":
        button.setObjectName("primaryButton")
    
    button.setFont(CleanFonts.get_font(CleanFonts.FONT_NORMAL))
    return button
