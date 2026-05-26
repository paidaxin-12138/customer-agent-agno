"""
统一加载状态组件
提供一致的加载动画和提示
"""

from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QProgressBar
from PyQt6.QtGui import QFont


class LoadingWidget(QFrame):
    """加载状态组件"""
    
    def __init__(self, parent=None, text: str = "加载中..."):
        """
        初始化加载组件
        
        Args:
            parent: 父窗口
            text: 加载提示文字
        """
        super().__init__(parent)
        self.text = text
        self._setup_ui()
        self._apply_style()
        self._start_animation()
    
    def _setup_ui(self):
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 加载动画（用文字模拟）
        self.loading_label = QLabel("⏳")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_label.setFont(QFont("Arial", 32))
        layout.addWidget(self.loading_label, 0, Qt.AlignmentFlag.AlignCenter)
        
        # 加载文字
        self.text_label = QLabel(self.text)
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.text_label, 0, Qt.AlignmentFlag.AlignCenter)
        
        # 进度条（可选）
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # 不确定进度
        self.progress_bar.setMinimumWidth(200)
        layout.addWidget(self.progress_bar, 0, Qt.AlignmentFlag.AlignCenter)
    
    def _apply_style(self):
        """应用样式"""
        self.setStyleSheet("""
            QFrame {
                background-color: rgba(30, 30, 30, 0.9);
                border-radius: 12px;
            }
            
            QLabel {
                color: #FFFFFF;
                background: transparent;
            }
            
            QLabel:first-child {
                font-size: 32px;
            }
            
            QLabel:nth-child(2) {
                font-size: 14px;
                color: #8E8E93;
            }
            
            QProgressBar {
                background-color: #2C2C2E;
                border: none;
                border-radius: 4px;
                height: 4px;
                text-align: center;
            }
            
            QProgressBar::chunk {
                background-color: #007AFF;
                border-radius: 4px;
            }
        """)
    
    def _start_animation(self):
        """启动动画"""
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self._on_animation_timeout)
        self.animation_timer.start(500)
        self._dots = 0
    
    def _on_animation_timeout(self):
        """动画超时处理"""
        self._dots = (self._dots + 1) % 4
        dots = "." * self._dots
        self.text_label.setText(f"{self.text}{dots}")
    
    def set_text(self, text: str):
        """
        设置加载文字
        
        Args:
            text: 加载文字
        """
        self.text = text
        self.text_label.setText(text)
    
    def stop_animation(self):
        """停止动画"""
        if hasattr(self, 'animation_timer'):
            self.animation_timer.stop()


class LoadingOverlay(QWidget):
    """加载遮罩层"""
    
    def __init__(self, parent=None, text: str = "加载中..."):
        """
        初始化加载遮罩层
        
        Args:
            parent: 父窗口
            text: 加载文字
        """
        super().__init__(parent)
        self.loading_widget = LoadingWidget(self, text)
        self._setup_ui()
    
    def _setup_ui(self):
        """设置 UI"""
        self.setStyleSheet("background-color: rgba(0, 0, 0, 0.5);")
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.loading_widget)
        
        # 默认隐藏
        self.hide()
    
    def show_loading(self, text: str = ""):
        """
        显示加载
        
        Args:
            text: 加载文字
        """
        if text:
            self.loading_widget.set_text(text)
        self.show()
        self.raise_()
    
    def hide_loading(self):
        """隐藏加载"""
        self.hide()
        self.loading_widget.stop_animation()


# ========== 便捷函数 ==========

def show_loading(parent, text: str = "加载中..."):
    """
    显示加载状态
    
    Args:
        parent: 父窗口
        text: 加载文字
        
    Returns:
        LoadingOverlay 实例
    """
    overlay = LoadingOverlay(parent, text)
    overlay.show_loading()
    return overlay


def hide_loading(overlay):
    """
    隐藏加载状态
    
    Args:
        overlay: LoadingOverlay 实例
    """
    if overlay:
        overlay.hide_loading()
        overlay.deleteLater()
