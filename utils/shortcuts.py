"""
全局快捷键管理
提供常用操作的快捷键支持
"""

from PyQt6.QtCore import Qt, QShortcut
from PyQt6.QtGui import QKeySequence
from typing import Callable, Optional
from utils.logger_loguru import get_logger

logger = get_logger("Shortcuts")


class ShortcutManager:
    """快捷键管理器"""
    
    def __init__(self, parent):
        """
        初始化快捷键管理器
        
        Args:
            parent: 父窗口
        """
        self.parent = parent
        self.shortcuts = {}
        self._setup_shortcuts()
    
    def _setup_shortcuts(self):
        """设置所有快捷键"""
        
        # Ctrl+S - 保存
        self.register(
            key_sequence="Ctrl+S",
            callback=self._on_save,
            description="保存当前内容"
        )
        
        # Ctrl+F - 搜索
        self.register(
            key_sequence="Ctrl+F",
            callback=self._on_search,
            description="搜索"
        )
        
        # Ctrl+R - 刷新
        self.register(
            key_sequence="Ctrl+R",
            callback=self._on_refresh,
            description="刷新当前页面"
        )
        
        # F5 - 刷新
        self.register(
            key_sequence="F5",
            callback=self._on_refresh,
            description="刷新当前页面"
        )
        
        # Esc - 取消/关闭
        self.register(
            key_sequence="Esc",
            callback=self._on_escape,
            description="取消或关闭"
        )
        
        # Ctrl+1~5 - 快速切换模块
        for i in range(1, 6):
            self.register(
                key_sequence=f"Ctrl+{i}",
                callback=lambda idx=i: self._on_switch_module(idx),
                description=f"切换到模块 {i}"
            )
        
        # Ctrl+Enter - 发送消息
        self.register(
            key_sequence="Ctrl+Return",
            callback=self._on_send_message,
            description="发送消息"
        )
        
        # Ctrl+Shift+N - 新建会话
        self.register(
            key_sequence="Ctrl+Shift+N",
            callback=self._on_new_chat,
            description="新建会话"
        )
        
        logger.info(f"已注册 {len(self.shortcuts)} 个快捷键")
    
    def register(self, key_sequence: str, callback: Callable, description: str = ""):
        """
        注册快捷键
        
        Args:
            key_sequence: 快捷键序列 (如 "Ctrl+S")
            callback: 回调函数
            description: 描述信息
        """
        shortcut = QShortcut(QKeySequence(key_sequence), self.parent)
        shortcut.activated.connect(callback)
        
        self.shortcuts[key_sequence] = {
            "shortcut": shortcut,
            "callback": callback,
            "description": description
        }
        
        logger.debug(f"注册快捷键：{key_sequence} - {description}")
    
    def unregister(self, key_sequence: str):
        """
        注销快捷键
        
        Args:
            key_sequence: 快捷键序列
        """
        if key_sequence in self.shortcuts:
            del self.shortcuts[key_sequence]
            logger.debug(f"注销快捷键：{key_sequence}")
    
    # ========== 快捷键处理函数 ==========
    
    def _on_save(self):
        """保存当前内容"""
        logger.info("快捷键：保存 (Ctrl+S)")
        # 由具体界面实现
    
    def _on_search(self):
        """搜索"""
        logger.info("快捷键：搜索 (Ctrl+F)")
        # 由具体界面实现
    
    def _on_refresh(self):
        """刷新当前页面"""
        logger.info("快捷键：刷新 (Ctrl+R/F5)")
        # 由具体界面实现
    
    def _on_escape(self):
        """取消或关闭"""
        logger.info("快捷键：取消 (Esc)")
        # 由具体界面实现
    
    def _on_switch_module(self, index: int):
        """
        切换到模块
        
        Args:
            index: 模块索引 (1-5)
        """
        logger.info(f"快捷键：切换模块 {index} (Ctrl+{index})")
        # 由具体界面实现
    
    def _on_send_message(self):
        """发送消息"""
        logger.info("快捷键：发送消息 (Ctrl+Enter)")
        # 由具体界面实现
    
    def _on_new_chat(self):
        """新建会话"""
        logger.info("快捷键：新建会话 (Ctrl+Shift+N)")
        # 由具体界面实现
    
    def get_help_text(self) -> str:
        """
        获取快捷键帮助文本
        
        Returns:
            快捷键帮助文本
        """
        help_lines = ["=== 快捷键列表 ===", ""]
        
        for key, info in sorted(self.shortcuts.items()):
            desc = info.get("description", "")
            help_lines.append(f"{key:20} {desc}")
        
        return "\n".join(help_lines)


# ========== 便捷函数 ==========

def setup_shortcuts(parent):
    """
    为窗口设置快捷键
    
    Args:
        parent: 父窗口
        
    Returns:
        ShortcutManager 实例
    """
    return ShortcutManager(parent)


def show_shortcuts_help(parent):
    """
    显示快捷键帮助
    
    Args:
        parent: 父窗口
    """
    from PyQt6.QtWidgets import QMessageBox
    
    manager = getattr(parent, '_shortcut_manager', None)
    if manager:
        help_text = manager.get_help_text()
        QMessageBox.information(parent, "快捷键帮助", help_text)
    else:
        QMessageBox.warning(parent, "提示", "未找到快捷键管理器")
