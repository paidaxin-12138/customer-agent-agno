"""
macOS 风格设计系统
Apple-style Design System for Customer-Agent

设计语言：
- 大圆角 (12-16px)
- 毛玻璃效果 (侧边栏)
- 简洁图标
- 大留白
- 柔和阴影
- San Francisco 字体风格
- 统一的灰色调
"""

from PyQt6.QtGui import QFont, QColor, QPalette, QIcon, QPainter, QPainterPath
from PyQt6.QtCore import Qt, QRectF, QPropertyAnimation, QEasingCurve
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QGraphicsDropShadowEffect
from utils.logger_loguru import get_logger

logger = get_logger("MacOSDesign")

# ============ macOS 配色方案 ============

class MacOSColors:
    """macOS 配色方案"""
    
    # 系统主色 (蓝色)
    SYSTEM_BLUE = "#007AFF"
    SYSTEM_BLUE_HOVER = "#0056B3"
    SYSTEM_BLUE_PRESSED = "#004094"
    
    # 背景色
    WINDOW_BG = "#FFFFFF"
    SIDEBAR_BG = "#F5F5F7"  # 浅灰侧边栏
    SIDEBAR_BG_ACTIVE = "#FFFFFF"
    CARD_BG = "#FFFFFF"
    CONTENT_BG = "#FFFFFF"
    
    # 文字颜色
    TEXT_PRIMARY = "#1D1D1F"      # 主文字 (深灰黑)
    TEXT_SECONDARY = "#6E6E73"    # 次要文字 (中灰)
    TEXT_TERTIARY = "#86868B"     # 第三级文字 (浅灰)
    TEXT_PLACEHOLDER = "#C7C7CC"  # 占位文字
    
    # 边框和分隔线
    BORDER = "#D2D2D7"
    BORDER_LIGHT = "#E5E5EA"
    SEPARATOR = "#E5E5EA"
    
    # 状态色
    SUCCESS = "#34C759"    # 绿色
    WARNING = "#FF9500"    # 橙色
    ERROR = "#FF3B30"      # 红色
    INFO = "#007AFF"       # 蓝色
    
    # 阴影
    SHADOW_COLOR = "#000000"
    
    # 选中/悬停
    SELECTION_BG = "#E8F2FF"  # 浅蓝背景
    HOVER_BG = "#F5F5F7"      # 浅灰悬停


# ============ macOS 字体方案 ============

class MacOSFonts:
    """macOS 字体方案"""
    
    # 字体家族 (优先使用系统字体)
    FONT_FAMILY = "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', 'PingFang SC', 'Microsoft YaHei'"
    
    # 字号 (macOS 标准)
    FONT_TINY = 9
    FONT_CAPTION = 10
    FONT_SUBHEAD = 11
    FONT_BODY = 12
    FONT_CALL_OUT = 13
    FONT_HEADLINE = 15
    FONT_TITLE3 = 16
    FONT_TITLE2 = 18
    FONT_TITLE1 = 20
    FONT_LARGE_TITLE = 24
    
    @staticmethod
    def get_font(size=FONT_BODY, weight="normal"):
        """
        获取字体
        
        Args:
            size: 字号
            weight: 字重 (light, regular, medium, semibold, bold)
        """
        # 尝试使用系统字体
        font_names = [".SF NS Text", "SF Pro Text", "Helvetica Neue", "PingFang SC", "Microsoft YaHei"]
        
        for font_name in font_names:
            font = QFont(font_name, size)
            if font.exactMatch():
                break
        else:
            font = QFont("Microsoft YaHei", size)
        
        # 设置字重
        weight_map = {
            "light": QFont.Weight.Light,
            "regular": QFont.Weight.Normal,
            "medium": QFont.Weight.Medium,
            "semibold": QFont.Weight.DemiBold,
            "bold": QFont.Weight.Bold
        }
        font.setWeight(weight_map.get(weight, QFont.Weight.Normal))
        
        # 启用抗锯齿
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        
        return font


# ============ macOS 间距方案 ============

class MacOSSpacing:
    """macOS 间距方案"""
    
    SPACING_XS = 4
    SPACING_S = 8
    SPACING_M = 12
    SPACING_L = 16
    SPACING_XL = 20
    SPACING_XXL = 24
    SPACING_XXXL = 32
    
    # 边距
    MARGIN_WINDOW = 0      # 窗口无边距
    MARGIN_SIDEBAR = 8     # 侧边栏内边距
    MARGIN_CONTENT = 20    # 内容区内边距
    MARGIN_CARD = 16       # 卡片内边距


# ============ macOS 圆角方案 ============

class MacOSRadius:
    """macOS 圆角方案"""
    
    RADIUS_NONE = 0
    RADIUS_S = 4
    RADIUS_M = 8
    RADIUS_L = 10
    RADIUS_XL = 12
    RADIUS_XXL = 16
    RADIUS_XXXL = 20
    
    # 按钮圆角
    BUTTON_RADIUS = 8
    
    # 卡片圆角
    CARD_RADIUS = 12
    
    # 输入框圆角
    INPUT_RADIUS = 8


# ============ macOS 阴影方案 ============

class MacOSShadow:
    """macOS 阴影方案"""
    
    @staticmethod
    def apply_shadow(widget, blur=20, offset=(0, 2), opacity=0.1):
        """
        应用柔和阴影
        
        Args:
            widget: Qt 控件
            blur: 模糊半径
            offset: 偏移 (x, y)
            opacity: 不透明度
        """
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(blur)
        shadow.setOffset(offset[0], offset[1])
        shadow.setColor(QColor(0, 0, 0))
        
        # Qt 不直接支持阴影透明度，需要通过样式表模拟
        widget.setGraphicsEffect(shadow)
        
        return shadow


# ============ macOS 风格组件 ============

class MacOSSidebar(QFrame):
    """macOS 风格侧边栏"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("macosSidebar")
        self.setFixedWidth(240)
        self.setup_ui()
        self.apply_style()
    
    def setup_ui(self):
        """设置 UI"""
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(MacOSSpacing.SPACING_S)
        self.layout.setContentsMargins(
            MacOSSpacing.MARGIN_SIDEBAR,
            MacOSSpacing.MARGIN_SIDEBAR,
            MacOSSpacing.MARGIN_SIDEBAR,
            MacOSSpacing.MARGIN_SIDEBAR
        )
    
    def apply_style(self):
        """应用样式"""
        self.setStyleSheet("""
            QFrame#macosSidebar {
                background-color: #F5F5F7;
                border-radius: 0px;
            }
        """)


class MacOSSidebarItem(QFrame):
    """macOS 风格侧边栏项"""
    
    def __init__(self, icon, text, parent=None, selected=False):
        super().__init__(parent)
        self.setObjectName("macosSidebarItem")
        self.setFixedHeight(32)
        self.selected = selected
        self.setup_ui(icon, text)
        self.apply_style()
    
    def setup_ui(self, icon, text):
        """设置 UI"""
        self.layout = QHBoxLayout(self)
        self.layout.setSpacing(MacOSSpacing.SPACING_M)
        self.layout.setContentsMargins(12, 4, 12, 4)
        
        # 图标
        if icon:
            self.icon_label = QLabel()
            self.icon_label.setFixedSize(16, 16)
            self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.layout.addWidget(self.icon_label)
        
        # 文字
        self.text_label = QLabel(text)
        self.text_label.setFont(MacOSFonts.get_font(MacOSFonts.FONT_BODY))
        self.layout.addWidget(self.text_label, 1)
    
    def apply_style(self):
        """应用样式"""
        if self.selected:
            self.setStyleSheet("""
                QFrame#macosSidebarItem {
                    background-color: #FFFFFF;
                    border-radius: 6px;
                }
                QLabel {
                    color: #1D1D1F;
                    font-weight: 500;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame#macosSidebarItem {
                    background-color: transparent;
                    border-radius: 6px;
                }
                QFrame#macosSidebarItem:hover {
                    background-color: #E5E5EA;
                }
                QLabel {
                    color: #6E6E73;
                }
                QFrame#macosSidebarItem:hover QLabel {
                    color: #1D1D1F;
                }
            """)
    
    def set_selected(self, selected):
        """设置选中状态"""
        self.selected = selected
        self.apply_style()


class MacOSButton(QPushButton):
    """macOS 风格按钮"""
    
    def __init__(self, text, parent=None, variant="primary"):
        super().__init__(text, parent)
        self.variant = variant
        self.setObjectName("macosButton")
        self.setFont(MacOSFonts.get_font(MacOSFonts.FONT_BODY, "medium"))
        self.setFixedHeight(36)
        self.apply_style()
    
    def apply_style(self):
        """应用样式"""
        if self.variant == "primary":
            self.setStyleSheet("""
                QPushButton#macosButton {
                    background-color: #007AFF;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 0 20px;
                }
                QPushButton#macosButton:hover {
                    background-color: #0056B3;
                }
                QPushButton#macosButton:pressed {
                    background-color: #004094;
                }
                QPushButton#macosButton:disabled {
                    background-color: #D2D2D7;
                    color: #86868B;
                }
            """)
        elif self.variant == "secondary":
            self.setStyleSheet("""
                QPushButton#macosButton {
                    background-color: #F5F5F7;
                    color: #1D1D1F;
                    border: none;
                    border-radius: 8px;
                    padding: 0 20px;
                }
                QPushButton#macosButton:hover {
                    background-color: #E5E5EA;
                }
                QPushButton#macosButton:pressed {
                    background-color: #D2D2D7;
                }
                QPushButton#macosButton:disabled {
                    background-color: #F5F5F7;
                    color: #C7C7CC;
                }
            """)


class MacOSCard(QFrame):
    """macOS 风格卡片"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("macosCard")
        self.setup_ui()
        self.apply_style()
    
    def setup_ui(self):
        """设置 UI"""
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(MacOSSpacing.SPACING_M)
        self.layout.setContentsMargins(
            MacOSSpacing.MARGIN_CARD,
            MacOSSpacing.MARGIN_CARD,
            MacOSSpacing.MARGIN_CARD,
            MacOSSpacing.MARGIN_CARD
        )
    
    def apply_style(self):
        """应用样式"""
        self.setStyleSheet("""
            QFrame#macosCard {
                background-color: #FFFFFF;
                border: 1px solid #E5E5EA;
                border-radius: 12px;
            }
            QFrame#macosCard:hover {
                border-color: #D2D2D7;
            }
        """)


class MacOSInput(QFrame):
    """macOS 风格输入框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("macosInputContainer")
        self.setup_ui()
        self.apply_style()
    
    def setup_ui(self):
        """设置 UI"""
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
    
    def apply_style(self):
        """应用样式"""
        self.setStyleSheet("""
            QFrame#macosInputContainer QLineEdit,
            QFrame#macosInputContainer QTextEdit,
            QFrame#macosInputContainer QPlainTextEdit {
                background-color: #FFFFFF;
                border: 1px solid #D2D2D7;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 13px;
                color: #1D1D1F;
                selection-background-color: #007AFF;
            }
            QLineEdit:focus,
            QTextEdit:focus,
            QPlainTextEdit:focus {
                border-color: #007AFF;
                border-width: 2px;
                padding: 7px 11px;
            }
            QLineEdit::placeholder {
                color: #C7C7CC;
            }
        """)


# ============ 应用设计系统 ============

def apply_macos_design(app):
    """
    应用 macOS 设计系统
    
    Args:
        app: QApplication 实例
    """
    logger.info("应用 macOS 设计系统...")
    
    # 设置全局字体
    app.setFont(MacOSFonts.get_font(MacOSFonts.FONT_BODY))
    
    # 设置调色板
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(MacOSColors.WINDOW_BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(MacOSColors.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Base, QColor(MacOSColors.WINDOW_BG))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(MacOSColors.SIDEBAR_BG))
    palette.setColor(QPalette.ColorRole.Text, QColor(MacOSColors.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Button, QColor(MacOSColors.SIDEBAR_BG))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(MacOSColors.TEXT_PRIMARY))
    app.setPalette(palette)
    
    # 应用全局样式
    apply_global_styles(app)
    
    logger.info("macOS 设计系统应用完成")


def apply_global_styles(app):
    """应用全局样式"""
    
    stylesheet = """
/* ============ 全局样式 ============ */

/* 主窗口 */
QMainWindow {
    background-color: #FFFFFF;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", "PingFang SC", "Microsoft YaHei";
    font-size: 13px;
    color: #1D1D1F;
}

/* ============ 按钮样式 ============ */

/* 主按钮 */
QPushButton#primaryButton {
    background-color: #007AFF;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 8px 20px;
    font-size: 13px;
    font-weight: 500;
}

QPushButton#primaryButton:hover {
    background-color: #0056B3;
}

QPushButton#primaryButton:pressed {
    background-color: #004094;
}

/* 普通按钮 */
QPushButton {
    background-color: #F5F5F7;
    color: #1D1D1F;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #E5E5EA;
}

QPushButton:pressed {
    background-color: #D2D2D7;
}

/* 危险按钮 */
QPushButton#dangerButton {
    background-color: #FF3B30;
    color: white;
}

QPushButton#dangerButton:hover {
    background-color: #D63228;
}

/* ============ 输入框样式 ============ */

QLineEdit,
QTextEdit,
QPlainTextEdit {
    background-color: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: #1D1D1F;
    selection-background-color: #007AFF;
}

QLineEdit:focus,
QTextEdit:focus,
QPlainTextEdit:focus {
    border-color: #007AFF;
    border-width: 2px;
    padding: 7px 11px;
}

QLineEdit:disabled,
QTextEdit:disabled {
    background-color: #F5F5F7;
    color: #86868B;
}

QLineEdit::placeholder {
    color: #C7C7CC;
}

/* ============ 标签样式 ============ */

QLabel {
    color: #1D1D1F;
    font-size: 13px;
    background: transparent;
}

QLabel#titleLabel {
    font-size: 20px;
    font-weight: 600;
    color: #1D1D1F;
}

QLabel#subtitleLabel {
    font-size: 13px;
    color: #6E6E73;
}

QLabel#sectionTitle {
    font-size: 15px;
    font-weight: 600;
    color: #1D1D1F;
    padding: 8px 0;
}

/* ============ 卡片容器 ============ */

QFrame#cardFrame {
    background-color: #FFFFFF;
    border: 1px solid #E5E5EA;
    border-radius: 12px;
    padding: 16px;
}

QFrame#cardFrame:hover {
    border-color: #D2D2D7;
}

/* ============ 列表样式 ============ */

QListView,
QListWidget {
    background-color: #FFFFFF;
    border: 1px solid #E5E5EA;
    border-radius: 8px;
    outline: none;
    show-decoration-selected: 1;
}

QListView::item,
QListWidget::item {
    padding: 8px 12px;
    border-radius: 6px;
    margin: 2px 4px;
}

QListView::item:hover,
QListWidget::item:hover {
    background-color: #F5F5F7;
}

QListView::item:selected,
QListWidget::item:selected {
    background-color: #E8F2FF;
    color: #007AFF;
}

/* ============ 表格样式 ============ */

QTableView,
QTableWidget {
    background-color: #FFFFFF;
    alternate-background-color: #F5F5F7;
    border: 1px solid #E5E5EA;
    border-radius: 8px;
    gridline-color: #E5E5EA;
    selection-background-color: #E8F2FF;
    selection-color: #007AFF;
}

QTableView::item,
QTableWidget::item {
    padding: 8px;
}

QHeaderView::section {
    background-color: #F5F5F7;
    color: #6E6E73;
    font-weight: 600;
    padding: 8px;
    border: none;
    border-bottom: 1px solid #D2D2D7;
    font-size: 12px;
}

/* ============ 滚动条样式 ============ */

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

/* ============ 组合框样式 ============ */

QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 13px;
    min-height: 36px;
}

QComboBox:hover {
    border-color: #86868B;
}

QComboBox:focus {
    border-color: #007AFF;
    border-width: 2px;
    padding: 5px 11px;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #E5E5EA;
    border-radius: 8px;
    selection-background-color: #E8F2FF;
}

/* ============ 标签页样式 ============ */

QTabWidget::pane {
    background-color: #FFFFFF;
    border: none;
    top: -1px;
}

QTabBar::tab {
    background-color: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 16px;
    color: #6E6E73;
    font-weight: 500;
}

QTabBar::tab:hover {
    color: #007AFF;
}

QTabBar::tab:selected {
    color: #007AFF;
    border-bottom-color: #007AFF;
}

/* ============ 进度条样式 ============ */

QProgressBar {
    background-color: #F5F5F7;
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}

QProgressBar::chunk {
    background-color: #007AFF;
    border-radius: 4px;
}

/* ============ 复选框样式 ============ */

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

/* ============ 单选框样式 ============ */

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

/* ============ 工具提示样式 ============ */

QToolTip {
    background-color: #1D1D1F;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}

/* ============ 菜单样式 ============ */

QMenu {
    background-color: #FFFFFF;
    border: 1px solid #E5E5EA;
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
    background-color: #E5E5EA;
    margin: 4px 0;
}

/* ============ 分隔线 ============ */

QFrame#line {
    background-color: #E5E5EA;
    max-height: 1px;
}

/* ============ 侧边栏 ============ */

QFrame#macosSidebar {
    background-color: #F5F5F7;
}

QFrame#macosSidebarItem {
    background-color: transparent;
    border-radius: 6px;
}

QFrame#macosSidebarItem:hover {
    background-color: #E5E5EA;
}

QFrame#macosSidebarItem[selected="true"] {
    background-color: #FFFFFF;
}

QFrame#macosSidebarItem[selected="true"] QLabel {
    color: #1D1D1F;
    font-weight: 500;
}

    """
    
    app.setStyleSheet(stylesheet)
    logger.info("全局样式应用完成")


# ============ 便捷函数 ============

def create_card(parent, title=None, layout_type="vertical"):
    """创建 macOS 风格卡片"""
    from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel
    
    card = QFrame(parent)
    card.setObjectName("cardFrame")
    
    # 应用阴影
    MacOSShadow.apply_shadow(card, blur=20, offset=(0, 2), opacity=0.05)
    
    if layout_type == "vertical":
        layout = QVBoxLayout(card)
        layout.setSpacing(MacOSSpacing.SPACING_M)
    else:
        layout = QHBoxLayout(card)
        layout.setSpacing(MacOSSpacing.SPACING_M)
    
    layout.setContentsMargins(16, 16, 16, 16)
    
    if title:
        title_label = QLabel(title)
        title_label.setFont(MacOSFonts.get_font(MacOSFonts.FONT_TITLE3, "semibold"))
        layout.addWidget(title_label)
    
    return card, layout


def create_sidebar_item(icon, text, parent, selected=False):
    """创建 macOS 风格侧边栏项"""
    item = MacOSSidebarItem(icon, text, parent, selected)
    return item


def create_button(text, parent, variant="primary"):
    """创建 macOS 风格按钮"""
    button = MacOSButton(text, parent, variant)
    return button


def create_label(text, parent, type="normal"):
    """创建 macOS 风格标签"""
    from PyQt6.QtWidgets import QLabel
    
    label = QLabel(text, parent)
    
    if type == "title":
        label.setObjectName("titleLabel")
        label.setFont(MacOSFonts.get_font(MacOSFonts.FONT_TITLE1, "semibold"))
    elif type == "subtitle":
        label.setObjectName("subtitleLabel")
        label.setFont(MacOSFonts.get_font(MacOSFonts.FONT_BODY))
    elif type == "section":
        label.setObjectName("sectionTitle")
        label.setFont(MacOSFonts.get_font(MacOSFonts.FONT_HEADLINE, "semibold"))
    else:
        label.setFont(MacOSFonts.get_font(MacOSFonts.FONT_BODY))
    
    return label
