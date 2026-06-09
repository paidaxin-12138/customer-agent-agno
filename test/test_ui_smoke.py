# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""UI 冒烟：主窗口导航与聊天输入区（pytest-qt，无真实网络）。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def stub_db(monkeypatch):
    mock_db = MagicMock()
    mock_db.list_all_accounts_for_chat.return_value = []
    mock_db.get_total_unread_chat.return_value = 0
    mock_db.get_chat_session_summaries.return_value = []
    monkeypatch.setattr("ui.chat_ui.db_manager", mock_db)


def test_chat_live_widget_message_list_exists(qtbot, stub_db):
    from ui.chat_ui import ChatLiveWidget

    widget = ChatLiveWidget()
    qtbot.addWidget(widget)
    assert widget.msg_list_view is not None
    assert widget.input_edit is not None
    widget.input_edit.setPlainText("冒烟测试消息")
    assert "冒烟测试" in widget.input_edit.toPlainText()


def test_main_window_page_change_logic_unit(stub_db):
    """不实例化 FluentWindow，仅验证聊天页判定与离开聊天页时恢复 AI。"""
    from ui.main_ui import MainWindow

    win = MainWindow.__new__(MainWindow)
    win.live_chat_view = MagicMock()
    win.stackedWidget = MagicMock()
    win._navigation_ready = True
    win._chat_page_index = 1
    win.live_chat_view._restore_ai_for_current_if_manual = MagicMock()

    win.stackedWidget.currentWidget.return_value = win.live_chat_view
    win.stackedWidget.currentIndex.return_value = 1
    win._was_on_chat_page = True
    assert win._is_chat_page_active() is True

    win._apply_page_changed()
    win.live_chat_view._restore_ai_for_current_if_manual.assert_not_called()

    win.stackedWidget.currentWidget.return_value = MagicMock()
    win.stackedWidget.currentIndex.return_value = 2
    assert win._is_chat_page_active() is False

    win._apply_page_changed()
    win.live_chat_view._restore_ai_for_current_if_manual.assert_called_once()
