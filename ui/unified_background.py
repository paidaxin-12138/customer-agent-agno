"""
统一背景样式 - 强制所有子界面使用统一的 macOS 风格背景
确保所有模块背景色一致为白色
"""

from PyQt6.QtWidgets import QWidget, QFrame, QScrollArea, QListWidget, QTableWidget, QTextEdit
from PyQt6.QtGui import QPalette, QColor
from utils.logger_loguru import get_logger

logger = get_logger("UnifiedBackground")

# ============ 统一背景色 ============

class UnifiedColors:
    """统一颜色方案"""
    
    # 主背景 - 纯白
    MAIN_BG = "#FFFFFF"
    
    # 内容区背景 - 纯白
    CONTENT_BG = "#FFFFFF"
    
    # 卡片背景 - 纯白
    CARD_BG = "#FFFFFF"
    
    # 输入框背景 - 纯白
    INPUT_BG = "#FFFFFF"
    
    # 列表/表格背景 - 纯白
    LIST_BG = "#FFFFFF"
    TABLE_BG = "#FFFFFF"
    
    # 代码/日志背景 - 浅灰（对比度）
    CODE_BG = "#F5F5F7"
    LOG_BG = "#F5F5F7"
    
    # 聊天气泡
    CHAT_SELF_BG = "#E8F2FF"      # 自己 - 浅蓝
    CHAT_OTHER_BG = "#F5F5F7"     # 他人 - 浅灰
    
    # 边框
    BORDER = "#E5E5EA"
    BORDER_LIGHT = "#F0F0F0"


# ============ 应用统一背景 ============

def apply_unified_background(widget):
    """
    递归应用统一背景到所有子控件
    
    Args:
        widget: Qt 控件
    """
    # 设置当前控件背景
    _set_widget_background(widget)
    
    # 递归处理所有子控件
    for child in widget.children():
        if isinstance(child, QWidget):
            apply_unified_background(child)


def _set_widget_background(widget):
    """设置单个控件的背景"""
    
    # 跳过某些特殊控件
    if _should_skip(widget):
        return
    
    # 根据控件类型设置背景
    widget_type = type(widget).__name__
    
    if widget_type in ['QFrame', 'QWidget', 'QScrollArea']:
        _set_white_background(widget)
    
    elif widget_type in ['QListWidget', 'QTreeWidget', 'QTableWidget']:
        _set_list_background(widget)
    
    elif widget_type in ['QTextEdit', 'QPlainTextEdit']:
        # 检查是否是日志或代码编辑器
        if _is_log_editor(widget):
            _set_light_gray_background(widget)
        else:
            _set_white_background(widget)
    
    elif widget_type == 'QTextBrowser':
        _set_white_background(widget)


def _should_skip(widget):
    """判断是否应该跳过该控件"""
    
    # 不处理按钮（按钮有自己的样式）
    if type(widget).__name__ in ['QPushButton', 'QToolButton', 'QCheckBox', 'QRadioButton']:
        return True
    
    # 不处理输入框（输入框有自己的样式）
    if type(widget).__name__ in ['QLineEdit', 'QComboBox', 'QSpinBox', 'QDoubleSpinBox']:
        return True
    
    # 不处理标签（标签通常是透明的）
    if type(widget).__name__ == 'QLabel':
        return True
    
    # 不处理分割线
    if type(widget).__name__ == 'Line':
        return True
    
    return False


def _set_white_background(widget):
    """设置白色背景"""
    widget.setStyleSheet("""
        background-color: #FFFFFF;
        border: none;
    """)


def _set_list_background(widget):
    """设置列表/表格背景"""
    widget.setStyleSheet("""
        QListView, QListWidget, QTreeWidget, QTableWidget {
            background-color: #FFFFFF;
            border: 1px solid #E5E5EA;
            border-radius: 8px;
            outline: none;
        }
        
        QListView::item, QListWidget::item, QTreeWidget::item, QTableWidget::item {
            background-color: #FFFFFF;
            padding: 8px;
        }
        
        QListView::item:hover, QListWidget::item:hover {
            background-color: #F5F5F7;
        }
        
        QListView::item:selected, QListWidget::item:selected {
            background-color: #E8F2FF;
            color: #007AFF;
        }
        
        /* 表头 */
        QHeaderView::section {
            background-color: #F5F5F7;
            color: #6E6E73;
            font-weight: 600;
            padding: 8px;
            border: none;
            border-bottom: 1px solid #D2D2D7;
        }
        
        /* 表格交替行 */
        QTableWidget {
            alternate-background-color: #FAFAFA;
        }
    """)


def _set_light_gray_background(widget):
    """设置浅灰色背景（用于日志/代码）"""
    widget.setStyleSheet("""
        QTextEdit, QPlainTextEdit {
            background-color: #F5F5F7;
            border: 1px solid #E5E5EA;
            border-radius: 8px;
            padding: 8px;
            color: #1D1D1F;
            font-family: "SF Mono", "Monaco", "Consolas", monospace;
            font-size: 12px;
        }
    """)


def _is_log_editor(widget):
    """判断是否是日志编辑器"""
    
    # 检查对象名
    object_name = widget.objectName().lower()
    if 'log' in object_name or 'console' in object_name:
        return True
    
    # 检查父级对象名
    parent = widget.parent()
    while parent:
        if 'log' in parent.objectName().lower():
            return True
        parent = parent.parent()
    
    # 检查是否是只读（日志通常是只读的）
    if widget.isReadOnly():
        return True
    
    return False


# ============ 聊天界面专用样式 ============

def apply_chat_styles(widget):
    """应用聊天界面样式"""
    
    stylesheet = """
/* 聊天容器 */
QFrame#chatContainer {
    background-color: #FFFFFF;
    border: none;
}

/* 消息气泡 - 自己 */
QFrame#messageBubbleSelf {
    background-color: #E8F2FF;
    border-radius: 16px;
    border-top-right-radius: 4px;
    padding: 12px;
}

/* 消息气泡 - 他人 */
QFrame#messageBubbleOther {
    background-color: #F5F5F7;
    border-radius: 16px;
    border-top-left-radius: 4px;
    padding: 12px;
}

/* 消息时间 */
QLabel#messageTime {
    color: #86868B;
    font-size: 11px;
}

/* 消息内容 */
QLabel#messageContent {
    color: #1D1D1F;
    font-size: 13px;
    background: transparent;
}

/* 输入框 */
QTextEdit#chatInput {
    background-color: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
    padding: 8px 12px;
}

QTextEdit#chatInput:focus {
    border-color: #007AFF;
    border-width: 2px;
    padding: 7px 11px;
}
    """
    
    widget.setStyleSheet(widget.styleSheet() + stylesheet)


# ============ 知识库界面专用样式 ============

def apply_knowledge_styles(widget):
    """应用知识库界面样式"""
    
    stylesheet = """
/* 知识库容器 */
QFrame#knowledgeContainer {
    background-color: #FFFFFF;
    border: none;
}

/* 知识卡片 */
QFrame#knowledgeCard {
    background-color: #FFFFFF;
    border: 1px solid #E5E5EA;
    border-radius: 12px;
    padding: 16px;
}

QFrame#knowledgeCard:hover {
    border-color: #D2D2D7;
    background-color: #FAFAFA;
}

/* 知识标题 */
QLabel#knowledgeTitle {
    color: #1D1D1F;
    font-size: 15px;
    font-weight: 600;
    background: transparent;
}

/* 知识内容 */
QLabel#knowledgeContent {
    color: #6E6E73;
    font-size: 13px;
    background: transparent;
}

/* 文档列表 */
QListWidget#documentList {
    background-color: #FFFFFF;
    border: 1px solid #E5E5EA;
    border-radius: 8px;
}

QListWidget#documentList::item {
    background-color: #FFFFFF;
    padding: 12px;
    border-bottom: 1px solid #F0F0F0;
}

QListWidget#documentList::item:hover {
    background-color: #F5F5F7;
}

QListWidget#documentList::item:selected {
    background-color: #E8F2FF;
    color: #007AFF;
}
    """
    
    widget.setStyleSheet(widget.styleSheet() + stylesheet)


# ============ 日志界面专用样式 ============

def apply_log_styles(widget):
    """应用日志界面样式"""
    
    stylesheet = """
/* 日志容器 */
QFrame#logContainer {
    background-color: #F5F5F7;
    border: none;
}

/* 日志文本框 */
QTextEdit#logText, QPlainTextEdit#logText {
    background-color: #FFFFFF;
    border: 1px solid #E5E5EA;
    border-radius: 8px;
    padding: 12px;
    color: #1D1D1F;
    font-family: "SF Mono", "Monaco", "Consolas", monospace;
    font-size: 12px;
    line-height: 1.5;
}

/* 日志级别颜色 */
QTextEdit#logText .log-info { color: #007AFF; }
QTextEdit#logText .log-warning { color: #FF9500; }
QTextEdit#logText .log-error { color: #FF3B30; }
QTextEdit#logText .log-success { color: #34C759; }

/* 日志时间戳 */
QTextEdit#logText .timestamp { color: #86868B; }
    """
    
    widget.setStyleSheet(widget.styleSheet() + stylesheet)


# ============ 全局应用 ============

def apply_all_unified_styles(root_widget):
    """
    全局应用所有统一样式
    
    Args:
        root_widget: 根控件（通常是 MainWindow）
    """
    logger.info("应用统一背景样式...")
    
    # 递归应用背景
    apply_unified_background(root_widget)
    
    # 应用特殊界面样式
    # 查找聊天界面
    chat_widgets = root_widget.findChildren(QWidget, "chatContainer")
    for widget in chat_widgets:
        apply_chat_styles(widget)
    
    # 查找知识库界面
    knowledge_widgets = root_widget.findChildren(QWidget, "knowledgeContainer")
    for widget in knowledge_widgets:
        apply_knowledge_styles(widget)
    
    # 查找日志界面
    log_widgets = root_widget.findChildren(QWidget, "logContainer")
    for widget in log_widgets:
        apply_log_styles(widget)
    
    logger.info("统一背景样式应用完成")


# ============ 便捷函数 ============

def force_white_background(widget):
    """强制设置白色背景"""
    widget.setStyleSheet("""
        background-color: #FFFFFF;
        border: none;
    """)


def force_list_background(widget):
    """强制设置列表白色背景"""
    widget.setStyleSheet("""
        background-color: #FFFFFF;
        border: 1px solid #E5E5EA;
        border-radius: 8px;
    """)


def force_log_background(widget):
    """强制设置日志浅灰背景"""
    widget.setStyleSheet("""
        background-color: #F5F5F7;
        border: none;
    """)
