"""
空状态提示组件
用于在数据为空时显示友好的提示信息
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PyQt6.QtGui import QFont, QIcon
from qfluentwidgets import FluentIcon as FIF


class EmptyStateWidget(QFrame):
    """空状态提示组件"""
    
    def __init__(self, parent=None, title: str = "", subtitle: str = "", icon=None):
        """
        初始化空状态组件
        
        Args:
            parent: 父窗口
            title: 标题
            subtitle: 副标题
            icon: 图标（FluentIcon 或 QIcon）
        """
        super().__init__(parent)
        self.title = title
        self.subtitle = subtitle
        self.icon = icon or FIF.DOCUMENT
        self._setup_ui()
        self._apply_style()
    
    def _setup_ui(self):
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 图标
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(64, 64)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignCenter)
        
        # 标题
        self.title_label = QLabel(self.title or "暂无数据")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignCenter)
        
        # 副标题
        if self.subtitle:
            self.subtitle_label = QLabel(self.subtitle)
            self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.subtitle_label, 0, Qt.AlignmentFlag.AlignCenter)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet("""
            QFrame {
                background-color: transparent;
                border: none;
            }
            
            QLabel {
                color: #8E8E93;
                background: transparent;
            }
            
            QLabel:first-child {
                font-size: 48px;
                color: #C7C7CC;
            }
            
            QLabel:nth-child(2) {
                font-size: 18px;
                font-weight: 500;
                color: #6E6E73;
                margin-top: 16px;
            }
            
            QLabel:nth-child(3) {
                font-size: 13px;
                color: #8E8E93;
                margin-top: 8px;
            }
        """)
    
    def set_title(self, title: str):
        """
        设置标题
        
        Args:
            title: 标题文本
        """
        self.title_label.setText(title)
    
    def set_subtitle(self, subtitle: str):
        """
        设置副标题
        
        Args:
            subtitle: 副标题文本
        """
        self.subtitle_label.setText(subtitle)
    
    def set_icon(self, icon):
        """
        设置图标
        
        Args:
            icon: FluentIcon 或 QIcon
        """
        if isinstance(icon, QIcon):
            self.icon_label.setPixmap(icon.pixmap(64, 64))
        else:
            # FluentIcon
            self.icon_label.setPixmap(icon.icon().pixmap(64, 64))


# ========== 预设空状态 ==========

class EmptyChatWidget(EmptyStateWidget):
    """聊天空状态"""
    
    def __init__(self, parent=None):
        super().__init__(
            parent=parent,
            title="暂无会话",
            subtitle="选择一个账号开始聊天",
            icon=FIF.CHAT
        )


class EmptyKnowledgeWidget(EmptyStateWidget):
    """知识库空状态"""
    
    def __init__(self, parent=None):
        super().__init__(
            parent=parent,
            title="暂无知识",
            subtitle="导入商品知识或 FAQ 开始使用",
            icon=FIF.BOOK_SHELF
        )


class EmptyLogWidget(EmptyStateWidget):
    """日志空状态"""
    
    def __init__(self, parent=None):
        super().__init__(
            parent=parent,
            title="暂无日志",
            subtitle="操作后将显示日志记录",
            icon=FIF.DOCUMENT
        )


class EmptyAccountWidget(EmptyStateWidget):
    """账号空状态"""
    
    def __init__(self, parent=None):
        super().__init__(
            parent=parent,
            title="暂无账号",
            subtitle="添加店铺账号开始使用",
            icon=FIF.PEOPLE
        )


class EmptySearchWidget(EmptyStateWidget):
    """搜索空状态"""
    
    def __init__(self, parent=None):
        super().__init__(
            parent=parent,
            title="未找到结果",
            subtitle="尝试更换搜索关键词",
            icon=FIF.SEARCH
        )


# ========== 便捷函数 ==========

def show_empty_state(parent, title: str = "", subtitle: str = "", icon=None):
    """
    显示空状态
    
    Args:
        parent: 父窗口
        title: 标题
        subtitle: 副标题
        icon: 图标
        
    Returns:
        EmptyStateWidget 实例
    """
    widget = EmptyStateWidget(parent, title, subtitle, icon)
    return widget


def hide_empty_state(widget):
    """
    隐藏空状态
    
    Args:
        widget: EmptyStateWidget 实例
    """
    if widget:
        widget.hide()
