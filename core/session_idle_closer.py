# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
买家离线超时自动将会话标为已解决（status=closed）。
"""
from __future__ import annotations

import threading
from typing import List, Tuple

from PyQt6.QtCore import QObject, QTimer

from config import config
from database.db_manager import db_manager
from utils.logger_loguru import get_logger


class SessionIdleCloserService(QObject):
    """定时扫描 active 会话，买家最后一条消息超过阈值则 close。"""

    def __init__(self, parent=None, interval_ms: int = 60_000):
        super().__init__(parent)
        self.logger = get_logger("SessionIdleCloser")
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.run_once)
        self._scan_lock = threading.Lock()
        self._scan_running = False

    def start(self) -> None:
        if not config.get("chat.session_idle_resolve_enabled", True):
            return
        self._timer.start()
        self.logger.info("买家离线自动结案服务已启动")

    def stop(self) -> None:
        self._timer.stop()

    def run_once(self) -> int:
        """后台扫描 DB，避免阻塞 Qt 主线程导致界面无响应。"""
        if not config.get("chat.session_idle_resolve_enabled", True):
            return 0
        with self._scan_lock:
            if self._scan_running:
                return 0
            self._scan_running = True

        minutes = int(config.get("chat.session_idle_resolve_minutes", 5) or 5)
        idle_seconds = max(60, minutes * 60)

        def _work() -> None:
            closed: List[Tuple[int, str, str]] = []
            try:
                closed = db_manager.close_idle_chat_sessions(idle_seconds=idle_seconds)
            except Exception as e:
                self.logger.error(f"自动结案扫描失败: {e}")
            finally:
                with self._scan_lock:
                    self._scan_running = False
            if not closed:
                return
            try:
                from utils.qt_threading import run_on_main_thread

                run_on_main_thread(lambda: self._after_close(closed, minutes))
            except Exception as e:
                self.logger.debug(f"结案 UI 回调调度失败: {e}")

        threading.Thread(target=_work, daemon=True, name="SessionIdleClose").start()
        return 0

    def _after_close(
        self, closed: List[Tuple[int, str, str]], minutes: int
    ) -> None:
        self.logger.info(f"买家离线 {minutes} 分钟，已结案 {len(closed)} 个会话")
        self._notify_ui(closed)
        self._sync_ops_sessions()

    def _sync_ops_sessions(self) -> None:
        try:
            from database.ops_repository import OpsRepository

            OpsRepository(db_manager).sync_sessions_from_chat()
        except Exception as e:
            self.logger.debug(f"运营看板会话同步: {e}")

    def _notify_ui(self, closed: List[Tuple[int, str, str]]) -> None:
        """closed: [(account_id, buyer_uid, account_key), ...]"""
        try:
            from ui.conversation_hub import get_conversation_hub  # noqa: PLC0415

            hub = get_conversation_hub()
            for _aid, _buid, account_key in closed:
                hub.list_changed.emit(account_key)
        except Exception as e:
            self.logger.debug(f"结案后刷新 UI: {e}")
