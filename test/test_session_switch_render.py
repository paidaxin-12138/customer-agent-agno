"""会话切换时消息渲染抢占与状态一致性。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


from ui.chat.message_list_mixin import ChatMessageListMixin


class _Widget(ChatMessageListMixin):
    def __init__(self):
        self._current = None
        self._render_token = 0
        self._render_in_progress = False
        self._msg_render_pending = False
        self._msg_render_job = None
        self._msg_last_loaded_session_id = None
        self._msg_last_loaded_id = 0
        self._session_switch_token = 0
        self._active_session_switch_token = None
        self._session_click_inflight = False
        self._pending_session_click = None
        self.msg_list_view = MagicMock()
        self.msg_list_view.message_count.return_value = 3
        self.logger = MagicMock()

    def _page_size(self):
        return 50

    def _ensure_message_area(self):
        return True

    def _cancel_older_fetch(self):
        pass

    def _show_message_loading(self, total):
        pass

    def _show_message_loading_early(self):
        pass

    def _hide_message_loading(self):
        pass

    def _schedule_message_list_reflow(self):
        pass

    def _flush_after_render_refresh(self):
        pass

    def _scroll_messages_to_bottom(self):
        pass

    def _notify_message_load_success(self, _n):
        pass

    def _clear_messages(self):
        pass

    def _schedule_msg_render_tick(self, _delay_ms=0):
        pass


@pytest.fixture()
def widget():
    return _Widget()


def test_render_messages_preempts_inflight_render(widget):
    widget._current = {"session_id": 2, "buyer_nickname": "B"}
    widget._render_in_progress = True
    widget._msg_render_job = {"session_id": 1, "token": 0, "rows": [], "index": 0, "total": 0}
    widget._msg_last_loaded_session_id = 1

    with patch("ui.chat.message_list_mixin.db_manager") as db:
        db.get_chat_message_count.return_value = 1
        db.get_chat_messages_paginated.return_value = [
            {"id": 10, "sender_type": "customer", "content": "hi", "sent_at": None}
        ]
        widget._render_messages_from_db()

    assert widget._render_in_progress is True
    assert widget._msg_render_job is not None
    assert widget._msg_render_job["session_id"] == 2
    assert widget._render_token == 1


def test_render_tick_skips_stale_session(widget):
    widget._current = {"session_id": 9}
    widget._msg_render_job = {
        "session_id": 8,
        "token": widget._render_token,
        "rows": [],
        "index": 0,
        "total": 0,
        "buyer_letter": "买",
    }
    widget._render_in_progress = True
    widget._on_msg_render_tick()
    assert widget._msg_render_job is None
    assert widget._render_in_progress is False


def test_complete_render_reloads_pending_not_incremental(widget):
    widget._msg_render_pending = True
    widget._msg_render_job = None

    def _immediate(_ms, fn):
        fn()

    with patch("ui.chat.message_list_mixin.QTimer.singleShot", side_effect=_immediate):
        with patch.object(widget, "_render_messages_from_db") as render:
            widget._complete_message_render()
    render.assert_called_once()


def test_messages_match_current_session(widget):
    widget._current = {"session_id": 5}
    widget._msg_last_loaded_session_id = 5
    assert widget._messages_match_current_session() is True
    widget._msg_last_loaded_session_id = 4
    assert widget._messages_match_current_session() is False
