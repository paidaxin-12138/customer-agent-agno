"""
聊天同步服务占位：可扩展为轮询拼多多开放平台历史消息。
当前仅发出定时 tick，供界面按需刷新数据库会话列表。
"""
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from utils.logger_loguru import get_logger


class ChatSyncService(QObject):
    """后台轻量同步：默认定时触发 UI 刷新钩子。"""

    tick = pyqtSignal()

    def __init__(self, parent=None, interval_ms: int = 8000):
        super().__init__(parent)
        self.logger = get_logger("ChatSync")
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.tick.emit)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def sync_messages(self, account_id: int) -> int:
        """按账号触发一次历史同步准备流程。

        Returns:
            拉取到的会话条数（当前平台接口未接通时返回 0）。
        """
        try:
            from database.db_manager import db_manager
            from Channel.pinduoduo.utils.API.get_messages import GetMessages

            acc = db_manager.get_account_row_by_id(int(account_id))
            if not acc:
                return 0
            api = GetMessages(
                shop_id=str(acc.get("shop_id") or ""),
                user_id=str(acc.get("user_id") or ""),
                channel_name=str(acc.get("channel_name") or "pinduoduo"),
            )
            sessions = api.get_all_sessions() or []
            if sessions:
                self.logger.info(f"历史同步预拉取会话数: {len(sessions)} (account_id={account_id})")
            return len(sessions)
        except Exception as e:
            self.logger.debug(f"历史同步跳过: {e}")
            return 0
