# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""QListView 消息列表模型/委托测试。"""
import pytest

from utils.chat_image_cache import ChatImageCache

from ui.widgets.chat_message_list_view import (
    ChatMessageListModel,
    ChatMessageListView,
    ChatMessageRow,
)


@pytest.fixture(autouse=True)
def _reset_chat_image_cache_singleton():
    ChatImageCache._instance = None
    yield
    ChatImageCache._instance = None


def test_loading_placeholder_row(qtbot):
    view = ChatMessageListView()
    qtbot.addWidget(view)
    model = view.message_model
    assert model.rowCount() == 0
    view.set_loading_placeholder(True)
    assert model.rowCount() == 1
    row = model.data(model.index(0, 0), ChatMessageListModel.RowRole)
    assert isinstance(row, ChatMessageRow)
    assert row.is_loading_placeholder is True
    view.set_loading_placeholder(False)
    assert model.rowCount() == 0


def test_append_and_last_id(qtbot):
    view = ChatMessageListView()
    qtbot.addWidget(view)
    view.append_messages(
        [
            ChatMessageRow(msg_id=10, sender_type="customer", content="你好"),
            ChatMessageRow(msg_id=11, sender_type="human", content="在的"),
        ]
    )
    assert view.message_count() == 2
    assert view.last_message_id() == 11
