#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
日志管理界面
"""

import os
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional
from collections import deque
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QAbstractTableModel, QModelIndex
from PyQt6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QWidget,
                            QTextEdit, QMessageBox, QSplitter,
                            QTableView, QHeaderView, QApplication,
                            QStyledItemDelegate, QStyleOptionViewItem)
from PyQt6.QtGui import QFont, QTextCursor, QColor, QTextCharFormat, QBrush, QPainter
from qfluentwidgets import (CardWidget, SubtitleLabel, CaptionLabel, BodyLabel,
                           PushButton, StrongBodyLabel,
                           ComboBox, LineEdit, ScrollArea, FluentIcon as FIF,
                           InfoBar, InfoBarPosition, ToolButton, CheckBox)
from utils.logger_loguru import get_logger, logger, UILogHandler
from utils.dialogs import confirm_action


class LogHandler:
    """兼容性LogHandler类 - 实际使用UILogHandler"""

    def __init__(self, signal_emitter):
        # 使用新的UILogHandler
        self.ui_handler = UILogHandler()
        # 连接信号
        self.ui_handler.log_received.connect(signal_emitter.log_received)
        self.signal_emitter = signal_emitter
        self._installed = False
        self.level = "DEBUG"  # 默认级别

    def emit(self, record):
        """为了兼容性保留，实际不使用"""
        pass

    def install(self):
        """安装日志处理器"""
        if not self._installed:
            self.ui_handler.install()
            self._installed = True

    def uninstall(self):
        """卸载日志处理器"""
        if self._installed:
            self.ui_handler.uninstall()
            self._installed = False

    def setLevel(self, level):
        """设置日志级别（兼容性方法）"""
        self.level = level

    def setFormatter(self, formatter):
        """设置格式器（兼容性方法）"""
        # loguru不需要格式器，保留为兼容性
        pass


class LogSignalEmitter(QWidget):
    """日志信号发射器"""
    # 适配loguru的record类型
    log_received = pyqtSignal(str, str, object)  # level, message, record


class UILogManager:
    """UI日志管理器 - 适配loguru的日志处理器"""
    _instance = None
    _handlers = []

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def add_handler(self, handler):
        """添加UI处理器"""
        self._handlers.append(handler)

        # 使用新的安装方法
        if hasattr(handler, 'install'):
            handler.install()

    def remove_handler(self, handler):
        """移除UI处理器"""
        if handler in self._handlers:
            self._handlers.remove(handler)

        # 使用新的卸载方法
        if hasattr(handler, 'uninstall'):
            handler.uninstall()


class LogItem:
    """日志项数据结构"""
    def __init__(self, level: str, message: str, record):
        self.level = level
        self.message = message
        self.record = record
        self.formatted_text = ""
        self.timestamp = ""
        self.module = ""
        self.file_info = ""
        self._format_log_record()

    def _format_log_record(self):
        """格式化日志记录"""
        try:
            if isinstance(self.record, dict):
                # loguru record
                record_data = self.record
                time_obj = record_data.get('time', datetime.now())
                if hasattr(time_obj, 'strftime'):
                    self.timestamp = time_obj.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                file_info = record_data.get('file', {})
                filename = getattr(file_info, 'name', 'unknown') if hasattr(file_info, 'name') else str(file_info.get('name', 'unknown'))
                function = record_data.get('function', '')
                line = record_data.get('line', '')
                self.file_info = f"{filename}:{function}:{line}" if all([filename, function, line]) else filename
                self.module = record_data.get('extra', {}).get('module', record_data.get('name', ''))
            else:
                # 标准logging record
                time_obj = getattr(self.record, 'created', datetime.now())
                self.timestamp = time_obj.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                filename = os.path.basename(getattr(self.record, 'filename', 'unknown'))
                function = getattr(self.record, 'funcName', '')
                line = getattr(self.record, 'lineno', '')
                self.file_info = f"{filename}:{function}:{line}" if all([filename, function, line]) else filename
                self.module = getattr(self.record, 'module', getattr(self.record, 'name', 'unknown'))

            self.formatted_text = f"{self.timestamp} | {self.level:8} | {self.file_info} - {self.message}"
        except Exception:
            time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.formatted_text = f"{time_str} | {self.level:8} | - {self.message}"


class LogModel(QAbstractTableModel):
    """日志数据模型"""

    # 定义列角色
    TimestampRole = Qt.ItemDataRole.UserRole + 1
    LevelRole = Qt.ItemDataRole.UserRole + 2
    MessageRole = Qt.ItemDataRole.UserRole + 3
    ModuleRole = Qt.ItemDataRole.UserRole + 4
    FileInfoRole = Qt.ItemDataRole.UserRole + 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._logs = deque(maxlen=10000)  # 使用循环缓冲区，最多保存10000条日志
        self._filtered_logs = []
        self._headers = ["时间", "级别", "模块", "文件", "消息"]

    def rowCount(self, parent=QModelIndex()):
        return len(self._filtered_logs)

    def columnCount(self, parent=QModelIndex()):
        return len(self._headers)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._filtered_logs):
            return None

        log_item = self._filtered_logs[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return log_item.timestamp
            elif col == 1:
                return log_item.level
            elif col == 2:
                return log_item.module
            elif col == 3:
                return log_item.file_info
            elif col == 4:
                return log_item.message
        elif role == Qt.ItemDataRole.ToolTipRole:
            return log_item.formatted_text
        elif role == self.TimestampRole:
            return log_item.timestamp
        elif role == self.LevelRole:
            return log_item.level
        elif role == self.MessageRole:
            return log_item.message
        elif role == self.ModuleRole:
            return log_item.module
        elif role == self.FileInfoRole:
            return log_item.file_info
        elif role == Qt.ItemDataRole.ForegroundRole:
            # 深色主题下的日志级别颜色
            level_colors = {
                'DEBUG': QColor(138, 138, 152),
                'INFO': QColor(74, 222, 128),
                'WARNING': QColor(255, 179, 71),
                'ERROR': QColor(255, 107, 107),
                'CRITICAL': QColor(255, 82, 82)
            }
            return level_colors.get(log_item.level, QColor(232, 232, 237))

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._headers[section]
        return None

    def add_log(self, level: str, message: str, record):
        """添加日志"""
        log_item = LogItem(level, message, record)
        self._logs.append(log_item)

        # 如果没有过滤条件，直接添加到显示列表
        if not hasattr(self, '_filter') or self._filter is None:
            self._filtered_logs.append(log_item)
        else:
            # 检查是否通过过滤
            if self._filter(log_item):
                self._filtered_logs.append(log_item)

        # 限制显示的日志数量
        if len(self._filtered_logs) > 1000:
            self._filtered_logs = self._filtered_logs[-1000:]

        # 发出数据变更信号
        self.layoutChanged.emit()

    def set_filter(self, filter_func=None):
        """设置过滤器"""
        self._filter = filter_func
        self._filtered_logs = []

        if filter_func is None:
            # 无过滤，显示所有日志
            self._filtered_logs = list(self._logs)
        else:
            # 应用过滤
            for log_item in self._logs:
                if filter_func(log_item):
                    self._filtered_logs.append(log_item)

        self.layoutChanged.emit()

    def clear(self):
        """清空所有日志"""
        self._logs.clear()
        self._filtered_logs.clear()
        self.layoutChanged.emit()


class LogTableDelegate(QStyledItemDelegate):
    """自定义表格项渲染器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlight_text = ""

    def set_highlight(self, text: str):
        """设置高亮文本"""
        self.highlight_text = text.lower()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        """绘制表格项"""
        super().paint(painter, option, index)

        # 绘制高亮
        if self.highlight_text:
            text = index.data(Qt.ItemDataRole.DisplayRole)
            if text and self.highlight_text in text.lower():
                # 创建高亮画刷
                highlight_color = QColor(255, 255, 0, 50)  # 半透明黄色
                painter.fillRect(option.rect, highlight_color)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex):
        """计算项大小"""
        size = super().sizeHint(option, index)
        # 确保有足够的高度显示内容
        size.setHeight(max(size.height(), 24))
        return size


class LogTableView(QTableView):
    """优化的日志表格视图"""

    def __init__(self, parent=None):
        super().__init__(parent)

        # 设置模型
        self.setModel(LogModel())

        # 设置代理
        self.setItemDelegate(LogTableDelegate())

        # 设置表格属性
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableView.SelectionMode.SingleSelection)

        # 设置表头
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)

        # 设置列宽
        self.setColumnWidth(0, 160)  # 时间
        self.setColumnWidth(1, 80)   # 级别
        self.setColumnWidth(2, 120)  # 模块
        self.setColumnWidth(3, 200)  # 文件
        # 消息列自动拉伸

        # 设置样式 - Apple 深色模式统一配色
        self.setStyleSheet("""
            QTableView {
                background-color: #1E1E1E;
                alternate-background-color: #1E1E1E;
                color: #FFFFFF;
                gridline-color: #3A3A3C;
                border: 1px solid #3A3A3C;
                border-radius: 12px;
                selection-background-color: #007AFF33;
                selection-color: #FFFFFF;
            }
            QTableView::item {
                padding: 4px;
                border: none;
            }
            QTableView::item:selected {
                background-color: #007AFF33;
                color: #FFFFFF;
            }
            QHeaderView::section {
                background-color: #2C2C2E;
                color: #8E8E93;
                padding: 8px;
                border: none;
                border-right: 1px solid #3A3A3C;
                border-bottom: 1px solid #3A3A3C;
                font-weight: bold;
            }
        """)

    def set_highlight(self, text: str):
        """设置搜索高亮"""
        delegate = self.itemDelegate()
        if isinstance(delegate, LogTableDelegate):
            delegate.set_highlight(text)
            self.viewport().update()


class LogDisplayWidget(QWidget):
    """日志显示组件容器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        # 保存所有日志记录
        self.all_logs = []

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 创建表格视图
        self.log_table = LogTableView()
        layout.addWidget(self.log_table)

    def append_log(self, level: str, message: str, record):
        """添加日志"""
        # 保存到所有日志列表
        log_item = (level, message, record)
        self.all_logs.append(log_item)

        # 直接添加到模型（模型会根据当前过滤器进行处理）
        self.log_table.model().add_log(level, message, record)

    def clear_all(self):
        """清空所有日志"""
        self.all_logs.clear()
        self.log_table.model().clear()

    def set_filter(self, filter_dict):
        """设置过滤条件"""
        level_filter = filter_dict.get('level', '全部')

        # 创建过滤器函数
        def filter_func(log_item):
            # 级别过滤
            if level_filter != '全部' and level_filter != log_item.level:
                return False

            # 搜索过滤
            search_text = filter_dict.get('search', '').strip()
            if search_text and search_text.lower() not in log_item.formatted_text.lower():
                return False

            return True

        # 清空模型
        model = self.log_table.model()
        model.clear()

        # 重新添加所有日志，让过滤器决定是否显示
        for level, message, record in self.all_logs:
            model.add_log(level, message, record)

        # 应用过滤器到模型
        model.set_filter(filter_func)

        # 设置搜索高亮
        search_text = filter_dict.get('search', '').strip()
        self.log_table.set_highlight(search_text if search_text else "")
    
    

class LogFilterWidget(CardWidget):
    """日志过滤控制组件"""

    filter_changed = pyqtSignal(dict)  # 过滤条件改变信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUI()
        self.connectSignals()

    def setupUI(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # 标题
        title_label = StrongBodyLabel("日志过滤")
        layout.addWidget(title_label)

        # 日志级别过滤
        level_layout = QHBoxLayout()
        level_label = CaptionLabel("日志级别:")
        level_label.setFixedWidth(60)

        self.level_combo = ComboBox()
        self.level_combo.addItems(["全部", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.level_combo.setCurrentText("全部")
        self.level_combo.setFixedSize(120, 40)

        level_layout.addWidget(level_label)
        level_layout.addWidget(self.level_combo)
        level_layout.addStretch()

        # 搜索框
        search_layout = QHBoxLayout()
        search_label = CaptionLabel("搜索:")
        search_label.setFixedWidth(60)

        self.search_edit = LineEdit()
        self.search_edit.setPlaceholderText("输入关键词搜索...")
        self.search_edit.setFixedHeight(40)

        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_edit)

        # 自动滚动开关
        self.auto_scroll_check = CheckBox("自动滚动")
        self.auto_scroll_check.setChecked(True)

        # 添加到布局
        layout.addLayout(level_layout)
        layout.addLayout(search_layout)
        layout.addWidget(self.auto_scroll_check)

    def connectSignals(self):
        """连接信号"""
        self.level_combo.currentTextChanged.connect(self.emit_filter_changed)
        self.search_edit.textChanged.connect(self.emit_filter_changed)
        self.auto_scroll_check.stateChanged.connect(self.emit_filter_changed)

    def emit_filter_changed(self):
        """发射过滤条件改变信号"""
        filter_dict = {
            'level': self.level_combo.currentText(),
            'search': self.search_edit.text(),
            'auto_scroll': self.auto_scroll_check.isChecked()
        }
        self.filter_changed.emit(filter_dict)

    

class LogControlWidget(CardWidget):
    """日志控制组件"""

    clear_logs = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUI()
        self.connectSignals()

    def setupUI(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # 标题
        title_label = StrongBodyLabel("日志控制")
        layout.addWidget(title_label)

        # 清空按钮
        self.clear_btn = PushButton("清空")
        self.clear_btn.setIcon(FIF.DELETE)
        self.clear_btn.setFixedSize(120, 40)
        layout.addWidget(self.clear_btn)

    def connectSignals(self):
        """连接信号"""
        self.clear_btn.clicked.connect(self.clear_logs.emit)


class LogUI(QFrame):
    """日志管理界面"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger()

        self.setupUI()
        self.setupLogHandler()
        self.connectSignals()
        
    def setupUI(self):
        """设置UI（页边距与头部布局与关键词管理一致）"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(25)

        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(20)

        title_area = QWidget()
        title_layout = QVBoxLayout(title_area)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(5)
        title_label = SubtitleLabel("日志管理")
        subtitle_label = CaptionLabel("查看与筛选运行日志")
        title_layout.addWidget(title_label)
        title_layout.addWidget(subtitle_label)
        header_layout.addWidget(title_area)
        header_layout.addStretch()
        layout.addWidget(header_widget)

        # 主要内容区域
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(20)
        
        # 左侧控制面板
        left_panel = QWidget()
        left_panel.setFixedWidth(280)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)
        
        # 过滤控件
        self.filter_widget = LogFilterWidget()
        left_layout.addWidget(self.filter_widget)
        
        # 控制按钮
        self.control_widget = LogControlWidget()
        left_layout.addWidget(self.control_widget)
        
        left_layout.addStretch()
        
        # 右侧日志显示区域
        self.log_display = LogDisplayWidget()
        
        content_layout.addWidget(left_panel)
        content_layout.addWidget(self.log_display, 1)
        
        layout.addWidget(content_widget, 1)
        self.setObjectName("日志管理")
    
    def setupLogHandler(self):
        """设置日志处理器 - 只监听logger.py中的日志"""
        # 创建信号发射器 - 必须在主线程中创建
        self.signal_emitter = LogSignalEmitter(self)
        
        # 创建自定义日志处理器
        self.log_handler = LogHandler(self.signal_emitter)
        self.log_handler.setLevel("DEBUG")  # 确保捕获所有级别的日志

        # 设置格式（loguru不需要格式器，保留为兼容性）
        self.log_handler.setFormatter(None)
        
        # 先连接信号，再添加处理器 - 使用QueuedConnection确保线程安全
        self.signal_emitter.log_received.connect(
            self.handle_log_received, 
            Qt.ConnectionType.QueuedConnection
        )
        
        # 使用UILogManager添加处理器到loguru系统
        self.ui_log_manager = UILogManager()
        self.ui_log_manager.add_handler(self.log_handler)
    
    def connectSignals(self):
        """连接信号"""
        # 日志信号已在setupLogHandler中连接
        self.filter_widget.filter_changed.connect(self.apply_filter)
        self.control_widget.clear_logs.connect(self.clear_logs)
    
    def handle_log_received(self, level: str, message: str, record):
        """处理接收到的日志"""
        # 直接添加日志到显示，让LogDisplayWidget处理过滤
        self.log_display.append_log(level, message, record)
    
        
    def apply_filter(self, filter_dict: dict):
        """应用过滤条件"""
        # 直接将过滤条件传递给LogDisplayWidget
        self.log_display.set_filter(filter_dict)
    
    def clear_logs(self):
        """清空日志"""
        if confirm_action(
            self,
            "确认清空",
            "确定要清空所有日志吗？",
            confirm_text="确认清空",
            cancel_text="取消",
            destructive=True,
        ):
            self.log_records.clear()
            self.log_display.clear_all()
            InfoBar.success(
                title="清空成功",
                content="所有日志已清空",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
    
    
    def closeEvent(self, event):
        """关闭事件"""
        # 从logger.py的logger中移除日志处理器
        self.ui_log_manager.remove_handler(self.log_handler)
        super().closeEvent(event) 