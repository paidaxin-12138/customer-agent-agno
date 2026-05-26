"""
Apple 风格完整设计系统
完整的视觉层次和对比度
确保外框、背景、字体都清晰可见
"""

from PyQt6.QtGui import QFont, QColor, QPalette
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QFrame
from utils.logger_loguru import get_logger

logger = get_logger("AppleStyle")

# ============ 完整的颜色系统 ============

class AppleColors:
    """
    Apple 完整颜色系统
    确保每个元素都有清晰的对比度
    """
    
    # ========== 主色调 ==========
    PRIMARY_BLUE = "#007AFF"        # 苹果蓝
    PRIMARY_HOVER = "#0056B3"       # 深蓝（悬停）
    PRIMARY_PRESSED = "#004094"     # 更深（按下）
    
    # ========== 背景色层次 ==========
    # 窗口背景 - 浅灰（作为底色）
    WINDOW_BG = "#F5F5F7"
    
    # 侧边栏背景 - 更浅的灰
    SIDEBAR_BG = "#EBEBF0"
    SIDEBAR_HOVER = "#D1D1D6"
    SIDEBAR_SELECTED = "#FFFFFF"
    
    # 内容区背景 - 纯白（与窗口背景形成对比）
    CONTENT_BG = "#FFFFFF"
    CONTENT_HOVER = "#FAFAFA"
    
    # 卡片背景 - 纯白 + 阴影
    CARD_BG = "#FFFFFF"
    
    # 特殊区域背景
    LOG_BG = "#FFFFFF"              # 日志 - 白色
    CHAT_SELF_BG = "#007AFF"        # 自己消息 - 蓝色
    CHAT_OTHER_BG = "#E9E9EB"       # 他人消息 - 浅灰
    
    # ========== 字体颜色层次 ==========
    # 主字体 - 深灰黑（清晰可见）
    TEXT_PRIMARY = "#1D1D1F"        # 主文字
    TEXT_PRIMARY_INVERTED = "#FFFFFF"  # 反色（用于深色背景）
    
    # 次要字体 - 中灰
    TEXT_SECONDARY = "#6E6E73"      # 次要文字
    
    # 第三级字体 - 浅灰
    TEXT_TERTIARY = "#8E8E93"       # 提示文字
    
    # 禁用字体
    TEXT_DISABLED = "#C7C7CC"       # 禁用文字
    
    # ========== 边框和分隔线 ==========
    BORDER_STRONG = "#86868B"       # 强边框
    BORDER_NORMAL = "#D2D2D7"       # 普通边框
    BORDER_LIGHT = "#E5E5EA"        # 轻边框
    BORDER_MINIMAL = "#F0F0F0"      # 最小边框
    
    # 分隔线
    SEPARATOR = "#C6C6C8"
    
    # ========== 状态色 ==========
    SUCCESS = "#34C759"             # 成功绿
    SUCCESS_BG = "#E8F9ED"
    
    WARNING = "#FF9500"             # 警告橙
    WARNING_BG = "#FFF4E5"
    
    ERROR = "#FF3B30"               # 错误红
    ERROR_BG = "#FFE5E5"
    
    INFO = "#007AFF"                # 信息蓝
    INFO_BG = "#E8F2FF"
    
    # ========== 阴影 ==========
    SHADOW_COLOR = "rgba(0, 0, 0, 0.1)"
    SHADOW_COLOR_HEAVY = "rgba(0, 0, 0, 0.15)"


# ============ 完整的字体系统 ============

class AppleFonts:
    """Apple 完整字体系统"""
    
    # 字体家族
    FONT_FAMILY = "-apple-system, BlinkMacSystemFont, 'SF Pro', 'Helvetica Neue', 'PingFang SC', 'Microsoft YaHei'"
    
    # 字号
    SIZE_TINY = 9
    SIZE_CAPTION = 10
    SIZE_SUBHEAD = 11
    SIZE_BODY = 13
    SIZE_CALL_OUT = 14
    SIZE_HEADLINE = 15
    SIZE_TITLE3 = 16
    SIZE_TITLE2 = 18
    SIZE_TITLE1 = 20
    SIZE_LARGE_TITLE = 24
    
    # 字重
    WEIGHT_LIGHT = QFont.Weight.Light
    WEIGHT_REGULAR = QFont.Weight.Normal
    WEIGHT_MEDIUM = QFont.Weight.Medium
    WEIGHT_SEMIBOLD = QFont.Weight.DemiBold
    WEIGHT_BOLD = QFont.Weight.Bold
    
    @staticmethod
    def get_font(size=SIZE_BODY, weight=WEIGHT_REGULAR):
        """获取字体"""
        font_names = [".SF NS Text", "SF Pro", "Helvetica Neue", "PingFang SC", "Microsoft YaHei"]
        
        for font_name in font_names:
            font = QFont(font_name, size)
            if font.exactMatch():
                break
        else:
            font = QFont("Microsoft YaHei", size)
        
        font.setWeight(weight)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        
        return font


# ============ 完整的间距系统 ============

class AppleSpacing:
    """Apple 完整间距系统"""
    
    # 间距
    XS = 4
    S = 8
    M = 12
    L = 16
    XL = 20
    XXL = 24
    XXXL = 32
    
    # 边距
    MARGIN_SIDEBAR = 8
    MARGIN_CONTENT = 20
    MARGIN_CARD = 16
    MARGIN_WINDOW = 0
    
    # 内边距
    PADDING_BUTTON = (8, 16)
    PADDING_INPUT = (8, 12)
    PADDING_CARD = (16, 16)


# ============ 完整的圆角系统 ============

class AppleRadius:
    """Apple 完整圆角系统"""
    
    NONE = 0
    S = 4
    M = 6
    L = 8
    XL = 10
    XXL = 12
    XXXL = 16
    
    # 特定元素
    BUTTON = 8
    INPUT = 8
    CARD = 12
    SIDEBAR_ITEM = 6
    CHAT_BUBBLE = 16


# ============ 完整的全局样式 ============

APPLE_GLOBAL_STYLESHEET = """
/* ========================================
   Apple 风格全局样式表
   确保所有元素都有清晰的对比度
   ======================================== */

/* ========== 主窗口 ========== */
QMainWindow {
    background-color: #F5F5F7;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro", "Helvetica Neue", "PingFang SC", "Microsoft YaHei";
    font-size: 13px;
    color: #1D1D1F;
}

/* ========== 侧边栏 ========== */
QFrame#sidebarFrame {
    background-color: #EBEBF0;
    border-right: 1px solid #D2D2D7;
}

/* 侧边栏项 */
QFrame#sidebarItem {
    background-color: transparent;
    border-radius: 6px;
    min-height: 32px;
}

QFrame#sidebarItem:hover {
    background-color: #D1D1D6;
}

QFrame#sidebarItem[selected="true"] {
    background-color: #FFFFFF;
}

QFrame#sidebarItem QLabel {
    color: #6E6E73;
    font-size: 13px;
    font-weight: 400;
    background: transparent;
}

QFrame#sidebarItem:hover QLabel {
    color: #1D1D1F;
}

QFrame#sidebarItem[selected="true"] QLabel {
    color: #1D1D1F;
    font-weight: 500;
}

/* ========== 内容区 ========== */
QFrame#contentFrame {
    background-color: #FFFFFF;
    border: none;
}

/* ========== 卡片容器 ========== */
QFrame#cardFrame {
    background-color: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 12px;
    padding: 16px;
}

QFrame#cardFrame:hover {
    border-color: #86868B;
}

/* ========== 按钮 ========== */
/* 主按钮 */
QPushButton#primaryButton,
QPushButton[variant="primary"] {
    background-color: #007AFF;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 8px 20px;
    font-size: 13px;
    font-weight: 500;
    min-height: 36px;
}

QPushButton#primaryButton:hover,
QPushButton[variant="primary"]:hover {
    background-color: #0056B3;
}

QPushButton#primaryButton:pressed,
QPushButton[variant="primary"]:pressed {
    background-color: #004094;
}

QPushButton#primaryButton:disabled {
    background-color: #D2D2D7;
    color: #8E8E93;
}

/* 次按钮 */
QPushButton#secondaryButton,
QPushButton[variant="secondary"] {
    background-color: #FFFFFF;
    color: #1D1D1F;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
    padding: 8px 20px;
    font-size: 13px;
    font-weight: 500;
    min-height: 36px;
}

QPushButton#secondaryButton:hover,
QPushButton[variant="secondary"]:hover {
    background-color: #F5F5F7;
    border-color: #86868B;
}

QPushButton#secondaryButton:pressed,
QPushButton[variant="secondary"]:pressed {
    background-color: #E5E5EA;
}

/* 危险按钮 */
QPushButton#dangerButton,
QPushButton[variant="danger"] {
    background-color: #FF3B30;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 8px 20px;
    font-size: 13px;
    font-weight: 500;
}

QPushButton#dangerButton:hover {
    background-color: #D63228;
}

/* ========== 输入框 ========== */
QLineEdit,
QTextEdit,
QPlainTextEdit,
QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: #1D1D1F;
    selection-background-color: #007AFF;
    selection-color: #FFFFFF;
}

QLineEdit:focus,
QTextEdit:focus,
QPlainTextEdit:focus,
QComboBox:focus {
    border-color: #007AFF;
    border-width: 2px;
    padding: 7px 11px;
}

QLineEdit:disabled,
QTextEdit:disabled,
QPlainTextEdit:disabled {
    background-color: #F5F5F7;
    color: #8E8E93;
}

QLineEdit::placeholder {
    color: #8E8E93;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
    selection-background-color: #E8F2FF;
    selection-color: #007AFF;
}

/* ========== 标签 ========== */
QLabel {
    color: #1D1D1F;
    font-size: 13px;
    background: transparent;
}

QLabel#titleLabel {
    color: #1D1D1F;
    font-size: 20px;
    font-weight: 600;
}

QLabel#subtitleLabel {
    color: #6E6E73;
    font-size: 13px;
}

QLabel#sectionTitle {
    color: #1D1D1F;
    font-size: 15px;
    font-weight: 600;
}

QLabel#captionLabel {
    color: #8E8E93;
    font-size: 11px;
}

/* ========== 列表 ========== */
QListView,
QListWidget {
    background-color: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
    outline: none;
}

QListView::item,
QListWidget::item {
    background-color: #FFFFFF;
    padding: 8px 12px;
    border-radius: 6px;
    margin: 2px 4px;
    color: #1D1D1F;
}

QListView::item:hover,
QListWidget::item:hover {
    background-color: #F5F5F7;
    color: #1D1D1F;
}

QListView::item:selected,
QListWidget::item:selected {
    background-color: #E8F2FF;
    color: #007AFF;
}

/* ========== 表格 ========== */
QTableView,
QTableWidget {
    background-color: #FFFFFF;
    alternate-background-color: #FAFAFA;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
    gridline-color: #E5E5EA;
    selection-background-color: #E8F2FF;
    selection-color: #007AFF;
}

QTableView::item,
QTableWidget::item {
    padding: 8px;
    color: #1D1D1F;
}

QHeaderView::section {
    background-color: #F5F5F7;
    color: #6E6E73;
    font-weight: 600;
    font-size: 12px;
    padding: 8px;
    border: none;
    border-bottom: 1px solid #D2D2D7;
}

/* ========== 树形控件 ========== */
QTreeView {
    background-color: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
    outline: none;
}

QTreeView::item {
    padding: 6px 8px;
    color: #1D1D1F;
}

QTreeView::item:hover {
    background-color: #F5F5F7;
}

QTreeView::item:selected {
    background-color: #E8F2FF;
    color: #007AFF;
}

QTreeView::branch {
    background-color: transparent;
}

QTreeView::branch:has-siblings:!adjoins-item {
    border-left: 1px solid #D2D2D7;
}

/* ========== 滚动条 ========== */
QScrollBar:vertical {
    background-color: transparent;
    width: 14px;
    border-radius: 7px;
}

QScrollBar::handle:vertical {
    background-color: #D2D2D7;
    border-radius: 6px;
    min-height: 20px;
    margin: 2px;
}

QScrollBar::handle:vertical:hover {
    background-color: #86868B;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: transparent;
    height: 14px;
    border-radius: 7px;
}

QScrollBar::handle:horizontal {
    background-color: #D2D2D7;
    border-radius: 6px;
    min-width: 20px;
    margin: 2px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #86868B;
}

/* ========== 标签页 ========== */
QTabWidget::pane {
    background-color: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
    top: -1px;
}

QTabBar::tab {
    background-color: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 16px;
    color: #6E6E73;
    font-weight: 500;
    font-size: 13px;
}

QTabBar::tab:hover {
    color: #007AFF;
}

QTabBar::tab:selected {
    color: #007AFF;
    border-bottom-color: #007AFF;
}

/* ========== 进度条 ========== */
QProgressBar {
    background-color: #E5E5EA;
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}

QProgressBar::chunk {
    background-color: #007AFF;
    border-radius: 4px;
}

/* ========== 复选框 ========== */
QCheckBox {
    color: #1D1D1F;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid #D2D2D7;
    border-radius: 4px;
    background-color: #FFFFFF;
}

QCheckBox::indicator:checked {
    background-color: #007AFF;
    border-color: #007AFF;
}

QCheckBox::indicator:hover {
    border-color: #007AFF;
}

/* ========== 单选框 ========== */
QRadioButton {
    color: #1D1D1F;
    spacing: 8px;
}

QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid #D2D2D7;
    border-radius: 9px;
    background-color: #FFFFFF;
}

QRadioButton::indicator:checked {
    background-color: #007AFF;
    border-color: #007AFF;
}

/* ========== 工具提示 ========== */
QToolTip {
    background-color: #1D1D1F;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}

/* ========== 菜单 ========== */
QMenu {
    background-color: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 10px;
    padding: 8px 0;
}

QMenu::item {
    padding: 8px 20px;
    color: #1D1D1F;
}

QMenu::item:selected {
    background-color: #F5F5F7;
}

QMenu::separator {
    height: 1px;
    background-color: #D2D2D7;
    margin: 4px 0;
}

/* ========== 分组框 ========== */
QGroupBox {
    background-color: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 12px;
    margin-top: 12px;
    padding-top: 12px;
    font-weight: 600;
    color: #1D1D1F;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 8px;
    color: #1D1D1F;
}

/* ========== 分隔线 ========== */
QFrame#line,
QFrame[fluent-type="separator"] {
    background-color: #D2D2D7;
    max-height: 1px;
}

/* ========== 日志界面 ========== */
QFrame#logContainer {
    background-color: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 12px;
}

QTextEdit#logText,
QPlainTextEdit#logText {
    background-color: #FFFFFF;
    border: none;
    color: #1D1D1F;
    font-family: "SF Mono", "Monaco", "Consolas", monospace;
    font-size: 12px;
    padding: 12px;
    selection-background-color: #007AFF;
    selection-color: #FFFFFF;
}

/* ========== 聊天界面 ========== */
QFrame#chatContainer {
    background-color: #FFFFFF;
    border: none;
}

/* 消息气泡 - 自己（蓝色背景，白色文字） */
QFrame#messageBubbleSelf {
    background-color: #007AFF;
    border-radius: 16px;
    border-top-right-radius: 4px;
    padding: 12px;
}

QFrame#messageBubbleSelf QLabel {
    color: #FFFFFF;
    background: transparent;
}

QFrame#messageBubbleSelf QLabel#messageTime {
    color: rgba(255, 255, 255, 0.8);
    font-size: 11px;
}

/* 消息气泡 - 他人（浅灰背景，深色文字） */
QFrame#messageBubbleOther {
    background-color: #E9E9EB;
    border-radius: 16px;
    border-top-left-radius: 4px;
    padding: 12px;
}

QFrame#messageBubbleOther QLabel {
    color: #1D1D1F;
    background: transparent;
}

QFrame#messageBubbleOther QLabel#messageTime {
    color: #8E8E93;
    font-size: 11px;
}

/* 输入框 */
QTextEdit#chatInput {
    background-color: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
    padding: 8px 12px;
    color: #1D1D1F;
}

QTextEdit#chatInput:focus {
    border-color: #007AFF;
    border-width: 2px;
    padding: 7px 11px;
}

/* ========== 知识库界面 ========== */
QFrame#knowledgeContainer {
    background-color: #FFFFFF;
    border: none;
}

QFrame#knowledgeCard {
    background-color: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 12px;
    padding: 16px;
}

QFrame#knowledgeCard:hover {
    border-color: #86868B;
    background-color: #FAFAFA;
}

QLabel#knowledgeTitle {
    color: #1D1D1F;
    font-size: 15px;
    font-weight: 600;
    background: transparent;
}

QLabel#knowledgeContent {
    color: #6E6E73;
    font-size: 13px;
    background: transparent;
}

QListWidget#documentList {
    background-color: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
}

QListWidget#documentList::item {
    background-color: #FFFFFF;
    padding: 12px;
    border-bottom: 1px solid #E5E5EA;
    color: #1D1D1F;
}

QListWidget#documentList::item:hover {
    background-color: #F5F5F7;
}

QListWidget#documentList::item:selected {
    background-color: #E8F2FF;
    color: #007AFF;
}

/* ========== 设置界面 ========== */
QFrame#settingContainer {
    background-color: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 12px;
}

/* ========== 账号管理界面 ========== */
QFrame#accountContainer {
    background-color: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 12px;
}

/* ========== 状态指示器 ========== */
QLabel#statusOnline {
    color: #34C759;
    font-weight: 600;
}

QLabel#statusOffline {
    color: #8E8E93;
    font-weight: 600;
}

QLabel#statusBusy {
    color: #FF9500;
    font-weight: 600;
}

QLabel#statusError {
    color: #FF3B30;
    font-weight: 600;
}

"""

# ============ 应用设计系统 ============

def apply_apple_style(app):
    """
    应用完整的 Apple 风格
    
    Args:
        app: QApplication 实例
    """
    logger.info("应用 Apple 风格设计系统...")
    
    # 设置全局字体
    app.setFont(AppleFonts.get_font(AppleFonts.SIZE_BODY))
    
    # 设置调色板
    palette = QPalette()
    
    # 窗口
    palette.setColor(QPalette.ColorRole.Window, QColor(AppleColors.WINDOW_BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(AppleColors.TEXT_PRIMARY))
    
    # 基础
    palette.setColor(QPalette.ColorRole.Base, QColor(AppleColors.CONTENT_BG))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(AppleColors.SIDEBAR_BG))
    palette.setColor(QPalette.ColorRole.Text, QColor(AppleColors.TEXT_PRIMARY))
    
    # 按钮
    palette.setColor(QPalette.ColorRole.Button, QColor(AppleColors.SIDEBAR_BG))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(AppleColors.TEXT_PRIMARY))
    
    # 高亮
    palette.setColor(QPalette.ColorRole.Highlight, QColor(AppleColors.PRIMARY_BLUE))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(AppleColors.TEXT_PRIMARY_INVERTED))
    
    # 禁用
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(AppleColors.TEXT_DISABLED))
    
    app.setPalette(palette)
    
    # 应用全局样式
    app.setStyleSheet(APPLE_GLOBAL_STYLESHEET)
    
    logger.info("Apple 风格设计系统应用完成")


def get_style_for_widget(widget_type):
    """
    获取特定控件类型的样式
    
    Args:
        widget_type: 控件类型名称
        
    Returns:
        样式字符串
    """
    styles = {
        'card': """
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #D2D2D7;
                border-radius: 12px;
                padding: 16px;
            }
        """,
        
        'sidebar': """
            QFrame {
                background-color: #EBEBF0;
                border-right: 1px solid #D2D2D7;
            }
        """,
        
        'content': """
            QFrame {
                background-color: #FFFFFF;
                border: none;
            }
        """,
        
        'log': """
            QTextEdit, QPlainTextEdit {
                background-color: #FFFFFF;
                color: #1D1D1F;
                font-family: "SF Mono", "Monaco", "Consolas", monospace;
                font-size: 12px;
            }
        """,
        
        'chat_self': """
            QFrame {
                background-color: #007AFF;
                border-radius: 16px;
            }
            QLabel {
                color: #FFFFFF;
            }
        """,
        
        'chat_other': """
            QFrame {
                background-color: #E9E9EB;
                border-radius: 16px;
            }
            QLabel {
                color: #1D1D1F;
            }
        """
    }
    
    return styles.get(widget_type, "")
