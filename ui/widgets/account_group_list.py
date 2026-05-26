"""左侧账号分组列表：展示店铺·登录名及该账号下未读会话总数。"""
from __future__ import annotations

from typing import Dict, List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QSizePolicy

from database.db_manager import db_manager


class AccountGroupList(QListWidget):
    account_selected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.itemClicked.connect(self._on_item)
        self._accounts: List[Dict] = []

    def reload(self) -> None:
        self.clear()
        self._accounts = db_manager.list_all_accounts_for_chat()
        all_unread = sum(
            s.get("unread_count", 0)
            for s in db_manager.get_chat_sessions(None, "active")
        )
        it0 = QListWidgetItem(f"全部账号 ({all_unread})")
        it0.setData(Qt.ItemDataRole.UserRole, None)
        self.addItem(it0)
        for acc in self._accounts:
            uid = acc["id"]
            unread = sum(
                s.get("unread_count", 0)
                for s in db_manager.get_chat_sessions(uid, "active")
            )
            st = acc.get("status")
            st_txt = "在线" if st == 1 else ("离线" if st == 3 else "休息/未上线")
            label = f"{acc.get('shop_name','')} · {acc.get('username','')}\n{st_txt}  未读 {unread}"
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, uid)
            self.addItem(it)

    def _on_item(self, item: QListWidgetItem):
        self.account_selected.emit(item.data(Qt.ItemDataRole.UserRole))
