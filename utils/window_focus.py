"""主窗口从最小化/隐藏状态恢复并切到指定子页面。"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget


def restore_application_window(win: Optional[QWidget]) -> None:
    """取消最小化并置前（macOS / Windows 人工协助「去处理」用）。"""
    if win is None:
        return
    state = win.windowState()
    if state & Qt.WindowState.WindowMinimized:
        win.setWindowState(state & ~Qt.WindowState.WindowMinimized)
    if not win.isVisible():
        win.show()
    else:
        win.showNormal()
    win.raise_()
    win.activateWindow()
    app = QApplication.instance()
    if app is not None:
        try:
            app.setActiveWindow(win)
        except Exception:
            pass


def switch_main_window_to_widget(main: Optional[QWidget], target: QWidget) -> bool:
    """将 Fluent 主窗口 stackedWidget 切到 target 子界面。"""
    if main is None or target is None:
        return False
    switch = getattr(main, "switchTo", None)
    if callable(switch):
        try:
            switch(target)
            return True
        except Exception:
            pass
    sw = getattr(main, "stackedWidget", None)
    if sw is None:
        return False
    for i in range(sw.count()):
        if sw.widget(i) is target:
            sw.setCurrentIndex(i)
            return True
    return False
