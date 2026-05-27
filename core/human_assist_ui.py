"""
主窗口级人工协助弹窗：在 ChatLiveWidget 延迟加载前也能收到 assist_requested。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt

from core.human_assist_bus import get_human_assist_bus
from utils.logger_loguru import get_logger

if TYPE_CHECKING:
    from ui.main_ui import MainWindow

_log = get_logger("HumanAssistUI")
_wired = False


def setup_human_assist_popup(main_window: "MainWindow") -> None:
    """在 MainWindow 创建后调用一次，确保跨线程 emit 必有槽处理。"""
    global _wired
    if _wired:
        return
    bus = get_human_assist_bus(main_window)

    def _on_assist(payload: dict) -> None:
        view = getattr(main_window, "live_chat_view", None)
        handler = getattr(view, "_on_human_assist_requested", None)
        if callable(handler):
            handler(payload)
            return
        try:
            from ui.widgets.human_assist_dialog import HumanAssistDialog

            dlg = HumanAssistDialog(payload, main_window)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            _log.info("实时聊天未就绪，已在主窗口显示人工协助弹窗")
        except Exception as e:
            _log.error(f"独立人工协助弹窗失败: {e}", exc_info=True)

    bus.assist_requested.connect(_on_assist, Qt.ConnectionType.QueuedConnection)
    _wired = True
    _log.debug("人工协助弹窗总线已挂接到主窗口")
