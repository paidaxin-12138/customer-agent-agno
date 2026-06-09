# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
聊天同步：定时从 MMS 拉取会话列表，使软件与浏览器双端展示一致。
"""
from __future__ import annotations

import threading
from typing import Optional, Set

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from utils.logger_loguru import get_logger


class ChatSyncService(QObject):
    """后台 MMS 会话同步 + UI 刷新钩子。"""

    tick = pyqtSignal()
    sync_finished = pyqtSignal(int)

    def __init__(self, parent=None, interval_ms: Optional[int] = None):
        super().__init__(parent)
        self.logger = get_logger("ChatSync")
        from config import get_config

        if interval_ms is None:
            try:
                interval_ms = int(
                    get_config("chat.mms_session_sync_interval_ms", 15000) or 15000
                )
            except (TypeError, ValueError):
                interval_ms = 15000
        interval_ms = max(5000, min(int(interval_ms), 120_000))

        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._on_timer)
        self._worker_lock = threading.Lock()
        self._worker_running = False
        self._pending_accounts: Set[int] = set()

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _on_timer(self) -> None:
        self.tick.emit()
        self.schedule_sync_all()

    def schedule_sync_all(self) -> None:
        try:
            from core.mms_session_sync import list_account_ids_for_mms_sync

            for aid in list_account_ids_for_mms_sync():
                self.schedule_sync(int(aid))
        except Exception as e:
            self.logger.debug("schedule_sync_all: {}", e)

    def schedule_sync(self, account_id: int) -> None:
        """异步触发单账号 MMS 同步（不阻塞 UI）。"""
        try:
            from core.mms_session_sync import mms_session_sync_enabled

            if not mms_session_sync_enabled():
                return
        except Exception:
            return

        aid = int(account_id)
        with self._worker_lock:
            self._pending_accounts.add(aid)
            if self._worker_running:
                return
            self._worker_running = True

        def _run() -> None:
            total = 0
            try:
                from core.mms_session_sync import sync_mms_sessions_for_account

                while True:
                    with self._worker_lock:
                        if not self._pending_accounts:
                            break
                        next_id = self._pending_accounts.pop()
                    try:
                        total += sync_mms_sessions_for_account(next_id)
                    except Exception as e:
                        self.logger.debug(
                            "MMS 同步 worker account_id={}: {}", next_id, e
                        )
            finally:
                with self._worker_lock:
                    self._worker_running = False
                    still_pending = bool(self._pending_accounts)
                if still_pending:
                    self.schedule_sync_all()
                else:
                    try:
                        self.sync_finished.emit(int(total))
                    except Exception:
                        pass

        threading.Thread(target=_run, daemon=True, name="MmsSessionSync").start()

    def sync_messages(self, account_id: int) -> int:
        """兼容旧接口：调度异步同步。"""
        self.schedule_sync(int(account_id))
        return 0
