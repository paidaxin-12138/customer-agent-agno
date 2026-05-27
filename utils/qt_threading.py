"""
将 UI 相关回调调度到 Qt 主线程，避免 WebSocket/asyncio 线程直接 emit 信号或创建 QWidget 导致 macOS 崩溃。
"""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication

from utils.logger_loguru import get_logger

_log = get_logger("QtMainThread")

_bridge: Optional["_MainThreadBridge"] = None


class _MainThreadBridge(QObject):
    call = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.call.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)

    @pyqtSlot(object)
    def _dispatch(self, fn: object) -> None:
        if not callable(fn):
            return
        try:
            fn()
        except Exception as e:
            _log.error(f"主线程回调失败: {e}", exc_info=True)


def init_main_thread_bridge(parent: Optional[QObject] = None) -> None:
    """在 QApplication 创建后、于 GUI 主线程调用一次。"""
    global _bridge
    app = QApplication.instance()
    if app is None:
        return
    if _bridge is not None:
        return
    _bridge = _MainThreadBridge(parent or app)
    main = app.thread()
    if _bridge.thread() is not main:
        _bridge.moveToThread(main)
    _log.debug("主线程调度桥已初始化")


def run_on_main_thread(fn: Callable[[], None]) -> None:
    """从任意线程安全地在 Qt GUI 主线程执行 fn。"""
    app = QApplication.instance()
    if app is None:
        try:
            fn()
        except Exception as e:
            _log.error(f"无 QApplication 时执行回调失败: {e}")
        return

    if QThread.currentThread() is app.thread():
        fn()
        return

    if _bridge is None:
        _log.warning("主线程桥未初始化，跳过跨线程调度（请先在 app.main 调用 init_main_thread_bridge）")
        return

    _bridge.call.emit(fn)
