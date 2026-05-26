"""
深色 Apple 风格完整设计系统
Dark Mode Apple Style
确保所有界面都使用统一的深色配色
"""

from PyQt6.QtGui import QFont, QColor, QPalette
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from utils.logger_loguru import get_logger
from ui import apple_ui_tokens as APT

logger = get_logger("DarkAppleStyle")

# ============ 深色 Apple 配色系统 ============

class DarkAppleColors:
    """
    深色 Apple 配色（与 apple_ui_tokens / UI 规范一致）
    """

    WINDOW_BG = APT.BG_PRIMARY
    WINDOW_BG_SECONDARY = APT.BG_SECONDARY

    SIDEBAR_BG = APT.BG_SECONDARY
    SIDEBAR_HOVER = APT.BG_TERTIARY
    SIDEBAR_SELECTED = APT.ACCENT
    SIDEBAR_SELECTED_BG = APT.BG_TERTIARY

    CONTENT_BG = APT.BG_PRIMARY
    CARD_BG = APT.BG_SECONDARY
    CARD_HOVER = APT.BG_TERTIARY

    INPUT_BG = APT.BG_SECONDARY
    INPUT_BORDER = APT.BORDER
    INPUT_FOCUS_BORDER = APT.ACCENT

    TEXT_PRIMARY = APT.TEXT_PRIMARY
    TEXT_SECONDARY = APT.TEXT_SECONDARY
    TEXT_TERTIARY = APT.TEXT_TERTIARY
    TEXT_DISABLED = "#48484A"
    TEXT_LINK = APT.ACCENT

    BORDER_STRONG = "rgba(84, 84, 88, 0.45)"
    BORDER_NORMAL = APT.BORDER
    BORDER_LIGHT = APT.BORDER_LIGHT
    SEPARATOR = APT.BORDER_LIGHT

    BUTTON_PRIMARY = APT.ACCENT
    BUTTON_PRIMARY_HOVER = APT.ACCENT_HOVER
    BUTTON_SECONDARY = APT.BG_TERTIARY
    BUTTON_SECONDARY_TEXT = APT.TEXT_PRIMARY

    SUCCESS = APT.SUCCESS
    SUCCESS_BG = "#1C3D2A"

    WARNING = APT.WARNING
    WARNING_BG = "#3D361A"

    ERROR = APT.ERROR
    ERROR_BG = "#3D1F1F"

    INFO = APT.ACCENT
    INFO_BG = "#1A2F3D"

    CHAT_SELF_BG = APT.ACCENT
    CHAT_SELF_TEXT = APT.TEXT_PRIMARY
    CHAT_OTHER_BG = APT.BG_TERTIARY
    CHAT_OTHER_TEXT = APT.TEXT_PRIMARY

    TABLE_BG = APT.BG_PRIMARY
    TABLE_HEADER_BG = APT.BG_SECONDARY
    TABLE_ROW_HOVER = APT.BG_TERTIARY
    TABLE_ROW_SELECTED = "rgba(10, 132, 255, 0.22)"

    SCROLLBAR_BG = "transparent"
    SCROLLBAR_HANDLE = APT.BG_TERTIARY
    SCROLLBAR_HANDLE_HOVER = "#48484A"

    SHADOW_COLOR = "rgba(0, 0, 0, 0.28)"
    SHADOW_COLOR_HEAVY = "rgba(0, 0, 0, 0.45)"


# ============ 深色字体系统 ============

class DarkAppleFonts:
    """深色 Apple 字体系统"""

    FONT_FAMILY = (
        "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'SF Pro', "
        "'Helvetica Neue', 'PingFang SC', 'Segoe UI', Roboto, 'Microsoft YaHei'"
    )
    
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


# ============ 深色全局样式 ============

DARK_APPLE_STYLESHEET = """
/* ========================================
   深色 Apple 风格全局样式表
   Dark Mode Apple Style
   强制统一所有背景为 #1C1C1E
   ======================================== */

/* ========== 全局强制背景 ========== */
QWidget {
    background-color: #1C1C1E;
    color: #FFFFFF;
}

/* ========== 主窗口 ========== */
QMainWindow {
    background-color: #1C1C1E;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro", "Helvetica Neue", "PingFang SC", "Microsoft YaHei";
    font-size: 13px;
    color: #FFFFFF;
}

/* ========== 侧边栏 ========== */
QFrame#sidebarFrame {
    background-color: #2C2C2E;
    border-right: 1px solid rgba(84, 84, 88, 0.35);
}

QFrame#sidebarItem {
    background-color: transparent;
    border-radius: 6px;
    min-height: 32px;
}

QFrame#sidebarItem:hover {
    background-color: #3A3A3C;
}

QFrame#sidebarItem[selected="true"] {
    background-color: #3A3A3C;
}

QFrame#sidebarItem QLabel {
    color: #98989D;
    font-size: 13px;
    font-weight: 400;
    background: transparent;
}

QFrame#sidebarItem:hover QLabel {
    color: #FFFFFF;
}

QFrame#sidebarItem[selected="true"] QLabel {
    color: #FFFFFF;
    font-weight: 500;
}

/* ========== 内容区 ========== */
QFrame#contentFrame {
    background-color: #2C2C2E !important;
    border: 1px solid rgba(84, 84, 88, 0.35) !important;
    border-radius: 10px;
}

/* 强制所有内容区背景统一 */
QScrollArea, QFrame[fluent-type="scroll"], QWidget#contentWidget {
    background-color: #2C2C2E !important;
    border: 1px solid rgba(84, 84, 88, 0.28) !important;
}

/* ========== 卡片容器 ========== */
QFrame#cardFrame {
    background-color: #2C2C2E;
    border: 1px solid rgba(84, 84, 88, 0.35);
    border-radius: 10px;
    padding: 16px;
}

QFrame#cardFrame:hover {
    border-color: #636366;
    background-color: #3A3A3C;
}

/* ========== 按钮 ========== */
/* 主按钮 */
QPushButton#primaryButton,
QPushButton[variant="primary"] {
    background-color: #0A84FF;
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
    background-color: #0055CC;
}

QPushButton#primaryButton:pressed,
QPushButton[variant="primary"]:pressed {
    background-color: #004499;
}

QPushButton#primaryButton:disabled {
    background-color: #3A3A3C;
    color: #636366;
}

/* 次按钮 */
QPushButton#secondaryButton,
QPushButton[variant="secondary"] {
    background-color: #3A3A3C;
    color: #FFFFFF;
    border: 1px solid #48484A;
    border-radius: 8px;
    padding: 8px 20px;
    font-size: 13px;
    font-weight: 500;
    min-height: 36px;
}

QPushButton#secondaryButton:hover,
QPushButton[variant="secondary"]:hover {
    background-color: #48484A;
    border-color: #636366;
}

QPushButton#secondaryButton:pressed,
QPushButton[variant="secondary"]:pressed {
    background-color: #2C2C2E;
}

/* 危险按钮 */
QPushButton#dangerButton,
QPushButton[variant="danger"] {
    background-color: #FF453A;
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
    background-color: #1C1C1E;
    border: 1px solid #48484A;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: #FFFFFF;
    selection-background-color: #0A84FF;
    selection-color: #FFFFFF;
}

QLineEdit:focus,
QTextEdit:focus,
QPlainTextEdit:focus,
QComboBox:focus {
    border-color: #0A84FF;
    border-width: 2px;
    padding: 7px 11px;
}

QLineEdit:disabled,
QTextEdit:disabled,
QPlainTextEdit:disabled {
    background-color: #2C2C2E;
    color: #636366;
}

QLineEdit::placeholder {
    color: #636366;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: #2C2C2E;
    border: 1px solid #3A3A3C;
    border-radius: 8px;
    color: #FFFFFF;
    selection-background-color: #0A84FF;
    selection-color: #FFFFFF;
}

/* ========== 标签 ========== */
QLabel {
    color: #FFFFFF;
    font-size: 13px;
    background: transparent;
}

QLabel#titleLabel {
    color: #FFFFFF;
    font-size: 20px;
    font-weight: 600;
}

QLabel#subtitleLabel {
    color: #98989D;
    font-size: 13px;
}

QLabel#sectionTitle {
    color: #FFFFFF;
    font-size: 15px;
    font-weight: 600;
}

QLabel#captionLabel {
    color: #636366;
    font-size: 11px;
}

/* ========== 列表 ========== */
QListView,
QListWidget {
    background-color: #1C1C1E !important;
    border: 1px solid #48484A;
    border-radius: 8px;
    outline: none;
    color: #FFFFFF;
}

QListView::item,
QListWidget::item {
    background-color: #1C1C1E;
    padding: 8px 12px;
    border-radius: 6px;
    margin: 2px 4px;
    color: #FFFFFF;
}

QListView::item:hover,
QListWidget::item:hover {
    background-color: #2A2A2C;
    color: #FFFFFF;
}

QListView::item:selected,
QListWidget::item:selected {
    background-color: #0A84FF33;
    color: #FFFFFF;
}

/* ========== 表格 ========== */
QTableView,
QTableWidget {
    background-color: #1C1C1E !important;
    alternate-background-color: #1C1C1E !important;
    border: 1px solid #48484A;
    border-radius: 8px;
    gridline-color: #3A3A3C;
    selection-background-color: #0A84FF33;
    selection-color: #FFFFFF;
    color: #FFFFFF;
}

QTableView::item,
QTableWidget::item {
    background-color: #1C1C1E !important;
    padding: 8px;
    color: #FFFFFF;
}

QTableView::item,
QTableWidget::item {
    padding: 8px;
    color: #FFFFFF;
}

QHeaderView::section {
    background-color: #2C2C2E;
    color: #98989D;
    font-weight: 600;
    font-size: 12px;
    padding: 8px;
    border: none;
    border-bottom: 1px solid #3A3A3C;
}

/* ========== 树形控件 ========== */
QTreeView {
    background-color: #1C1C1E;
    border: 1px solid #3A3A3C;
    border-radius: 8px;
    outline: none;
    color: #FFFFFF;
}

QTreeView::item {
    padding: 6px 8px;
    color: #FFFFFF;
}

QTreeView::item:hover {
    background-color: #2A2A2C;
}

QTreeView::item:selected {
    background-color: #0A84FF33;
    color: #FFFFFF;
}

/* ========== 滚动条 ========== */
QScrollBar:vertical {
    background-color: transparent;
    width: 14px;
    border-radius: 7px;
}

QScrollBar::handle:vertical {
    background-color: #48484A;
    border-radius: 6px;
    min-height: 20px;
    margin: 2px;
}

QScrollBar::handle:vertical:hover {
    background-color: #636366;
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
    background-color: #48484A;
    border-radius: 6px;
    min-width: 20px;
    margin: 2px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #636366;
}

/* ========== 标签页 ========== */
QTabWidget::pane {
    background-color: #1C1C1E;
    border: 1px solid #3A3A3C;
    border-radius: 8px;
    top: -1px;
}

QTabBar::tab {
    background-color: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 16px;
    color: #98989D;
    font-weight: 500;
    font-size: 13px;
}

QTabBar::tab:hover {
    color: #FFFFFF;
}

QTabBar::tab:selected {
    color: #FFFFFF;
    border-bottom-color: #0A84FF;
}

/* ========== 进度条 ========== */
QProgressBar {
    background-color: #2C2C2E;
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
    color: #FFFFFF;
}

QProgressBar::chunk {
    background-color: #0A84FF;
    border-radius: 4px;
}

/* ========== 复选框 ========== */
QCheckBox {
    color: #FFFFFF;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid #48484A;
    border-radius: 4px;
    background-color: #1C1C1E;
}

QCheckBox::indicator:checked {
    background-color: #0A84FF;
    border-color: #0A84FF;
}

QCheckBox::indicator:hover {
    border-color: #0A84FF;
}

/* ========== 单选框 ========== */
QRadioButton {
    color: #FFFFFF;
    spacing: 8px;
}

QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid #48484A;
    border-radius: 9px;
    background-color: #1C1C1E;
}

QRadioButton::indicator:checked {
    background-color: #0A84FF;
    border-color: #0A84FF;
}

/* ========== 工具提示 ========== */
QToolTip {
    background-color: #2C2C2E;
    color: #FFFFFF;
    border: 1px solid #3A3A3C;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}

/* ========== 菜单 ========== */
QMenu {
    background-color: #2C2C2E;
    border: 1px solid #3A3A3C;
    border-radius: 10px;
    padding: 8px 0;
    color: #FFFFFF;
}

QMenu::item {
    padding: 8px 20px;
    color: #FFFFFF;
}

QMenu::item:selected {
    background-color: #3A3A3C;
}

QMenu::separator {
    height: 1px;
    background-color: #3A3A3C;
    margin: 4px 0;
}

/* ========== 分组框 ========== */
QGroupBox {
    background-color: #1C1C1E;
    border: 1px solid #3A3A3C;
    border-radius: 12px;
    margin-top: 12px;
    padding-top: 12px;
    font-weight: 600;
    color: #FFFFFF;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 8px;
    color: #FFFFFF;
}

/* ========== 分隔线 ========== */
QFrame#line,
QFrame[fluent-type="separator"] {
    background-color: #3A3A3C;
    max-height: 1px;
}

/* ========== 日志界面 ========== */
QFrame#logContainer {
    background-color: #2C2C2E !important;
    border: 2px solid #48484A !important;
    border-radius: 12px;
}

QTextEdit#logText,
QPlainTextEdit#logText {
    background-color: #1C1C1E !important;
    border: 1px solid #48484A;
    border-radius: 8px;
    color: #FFFFFF;
    font-family: "SF Mono", "Monaco", "Consolas", monospace;
    font-size: 12px;
    padding: 12px;
    selection-background-color: #0A84FF;
    selection-color: #FFFFFF;
}

/* ========== 聊天界面 ========== */
QFrame#chatContainer {
    background-color: #2C2C2E !important;
    border: 2px solid #48484A !important;
    border-radius: 12px;
}

/* 强制聊天列表和输入框背景统一 */
QListWidget#chatList {
    background-color: #1C1C1E !important;
    border: 1px solid #48484A !important;
    border-radius: 8px;
    color: #FFFFFF;
}

QTextEdit#chatInput,
QFrame#inputArea {
    background-color: #1C1C1E !important;
    border: 1px solid #48484A !important;
    border-radius: 8px;
    color: #FFFFFF;
}

/* 消息气泡 - 自己（蓝色背景，白色文字） */
QFrame#messageBubbleSelf {
    background-color: #0A84FF;
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

/* 消息气泡 - 他人（灰色背景，白色文字） */
QFrame#messageBubbleOther {
    background-color: #3A3A3C;
    border-radius: 16px;
    border-top-left-radius: 4px;
    padding: 12px;
}

QFrame#messageBubbleOther QLabel {
    color: #FFFFFF;
    background: transparent;
}

QFrame#messageBubbleOther QLabel#messageTime {
    color: #98989D;
    font-size: 11px;
}

/* 输入框 */
QTextEdit#chatInput {
    background-color: #1C1C1E;
    border: 1px solid #3A3A3C;
    border-radius: 8px;
    padding: 8px 12px;
    color: #FFFFFF;
}

QTextEdit#chatInput:focus {
    border-color: #0A84FF;
    border-width: 2px;
    padding: 7px 11px;
}

/* ========== 知识库界面 ========== */
QFrame#knowledgeContainer {
    background-color: #2C2C2E !important;
    border: 2px solid #48484A !important;
    border-radius: 12px;
}

/* 强制知识卡片背景统一 */
QFrame#knowledgeCard {
    background-color: #1C1C1E !important;
    border: 1px solid #48484A;
    border-radius: 8px;
    padding: 16px;
}

QFrame#knowledgeCard {
    background-color: #2C2C2E;
    border: 1px solid #3A3A3C;
    border-radius: 12px;
    padding: 16px;
}

QFrame#knowledgeCard:hover {
    border-color: #48484A;
    background-color: #3A3A3C;
}

QLabel#knowledgeTitle {
    color: #FFFFFF;
    font-size: 15px;
    font-weight: 600;
    background: transparent;
}

QLabel#knowledgeContent {
    color: #98989D;
    font-size: 13px;
    background: transparent;
}

QListWidget#documentList {
    background-color: #1C1C1E;
    border: 1px solid #3A3A3C;
    border-radius: 8px;
}

QListWidget#documentList::item {
    background-color: #1C1C1E;
    padding: 12px;
    border-bottom: 1px solid #2C2C2E;
    color: #FFFFFF;
}

QListWidget#documentList::item:hover {
    background-color: #2A2A2C;
}

QListWidget#documentList::item:selected {
    background-color: #0A84FF33;
    color: #FFFFFF;
}

/* ========== 设置界面 ========== */
QFrame#settingContainer {
    background-color: #1C1C1E;
    border: 1px solid #3A3A3C;
    border-radius: 12px;
}

/* ========== 账号管理界面 ========== */
QFrame#accountContainer {
    background-color: #1C1C1E;
    border: 1px solid #3A3A3C;
    border-radius: 12px;
}

/* ========== 状态指示器 ========== */
QLabel#statusOnline {
    color: #32D74B;
    font-weight: 600;
}

QLabel#statusOffline {
    color: #636366;
    font-weight: 600;
}

QLabel#statusBusy {
    color: #FFD60A;
    font-weight: 600;
}

QLabel#statusError {
    color: #FF453A;
    font-weight: 600;
}

/* ========== 工具栏按钮 ========== */
QToolButton {
    background-color: #3A3A3C;
    color: #FFFFFF;
    border: 1px solid #48484A;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
}

QToolButton:hover {
    background-color: #48484A;
    border-color: #636366;
}

QToolButton:pressed {
    background-color: #2C2C2E;
}

"""

# ============ 应用深色设计系统 ============

def apply_dark_apple_style(app):
    """
    应用深色 Apple 风格
    
    Args:
        app: QApplication 实例
    """
    logger.info("应用深色 Apple 风格设计系统...")
    
    # 设置全局字体
    app.setFont(DarkAppleFonts.get_font(DarkAppleFonts.SIZE_BODY))
    
    # 设置调色板
    palette = QPalette()
    
    # 窗口
    palette.setColor(QPalette.ColorRole.Window, QColor(DarkAppleColors.WINDOW_BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(DarkAppleColors.TEXT_PRIMARY))
    
    # 基础
    palette.setColor(QPalette.ColorRole.Base, QColor(DarkAppleColors.CONTENT_BG))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(DarkAppleColors.CARD_BG))
    palette.setColor(QPalette.ColorRole.Text, QColor(DarkAppleColors.TEXT_PRIMARY))
    
    # 按钮
    palette.setColor(QPalette.ColorRole.Button, QColor(DarkAppleColors.BUTTON_SECONDARY))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(DarkAppleColors.TEXT_PRIMARY))
    
    # 高亮
    palette.setColor(QPalette.ColorRole.Highlight, QColor(DarkAppleColors.BUTTON_PRIMARY))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(DarkAppleColors.TEXT_PRIMARY))
    
    # 禁用
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(DarkAppleColors.TEXT_DISABLED))
    
    app.setPalette(palette)
    
    # 应用全局样式
    app.setStyleSheet(DARK_APPLE_STYLESHEET)
    
    logger.info("深色 Apple 风格设计系统应用完成")
