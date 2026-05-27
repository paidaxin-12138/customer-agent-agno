"""
买家离线超时自动将会话标为已解决（status=closed）。
"""
from __future__ import annotations

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

    def start(self) -> None:
        if not config.get("chat.session_idle_resolve_enabled", True):
            return
        self._timer.start()
        self.logger.info("买家离线自动结案服务已启动")

    def stop(self) -> None:
        self._timer.stop()

    def run_once(self) -> int:
        if not config.get("chat.session_idle_resolve_enabled", True):
            return 0
        minutes = int(config.get("chat.session_idle_resolve_minutes", 5) or 5)
        idle_seconds = max(60, minutes * 60)
        try:
            closed = db_manager.close_idle_chat_sessions(idle_seconds=idle_seconds)
        except Exception as e:
            self.logger.error(f"自动结案扫描失败: {e}")
            return 0
        if not closed:
            return 0
        self.logger.info(f"买家离线 {minutes} 分钟，已结案 {len(closed)} 个会话")
        self._notify_ui(closed)
        self._sync_ops_sessions()
        return len(closed)

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
