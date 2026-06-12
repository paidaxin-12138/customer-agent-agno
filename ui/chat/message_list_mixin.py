# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""实时聊天 — 消息列表加载、分页与增量渲染（QListView + Delegate）。"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QEventLoop, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

from database.db_manager import db_manager
from qfluentwidgets import InfoBar, InfoBarPosition

from ui.chat import tokens as T
from ui.chat.dialogs import avatar_letter
from ui.chat.styles import loading_subtitle_style
from ui.widgets.chat_message_list_view import ChatMessageListModel, ChatMessageListView, ChatMessageRow


class _FetchOlderMessagesThread(QThread):
    loaded = pyqtSignal(list, int)
    failed = pyqtSignal()

    def __init__(self, session_id: int, limit: int, offset: int):
        super().__init__()
        self._session_id = session_id
        self._limit = limit
        self._offset = offset

    def run(self) -> None:
        try:
            rows = db_manager.get_chat_messages_paginated(
                self._session_id, self._limit, self._offset
            )
            self.loaded.emit(rows, self._offset)
        except Exception:
            self.failed.emit()


class ChatMessageListMixin:
    """依赖宿主提供 msg_list_view / _current / logger 等。"""

    def _ensure_message_area(self) -> bool:
        view = getattr(self, "msg_list_view", None)
        if view is None:
            return False
        try:
            return isinstance(view, ChatMessageListView)
        except RuntimeError:
            return False

    def _message_area_width(self) -> int:
        view = getattr(self, "msg_list_view", None)
        if view is not None:
            return max(view.viewport().width(), 320)
        return 320

    def _message_widget_count(self) -> int:
        view = getattr(self, "msg_list_view", None)
        if view is None:
            return 0
        return view.message_count()

    def _schedule_message_list_reflow(self) -> None:
        view = getattr(self, "msg_list_view", None)
        if view is not None and view.message_count() > 0:
            view.set_list_width(self._message_area_width())
            if hasattr(view, "relayout_items"):
                view.relayout_items()
            else:
                view.viewport().update()

    def _reflow_message_list(self) -> None:
        self._schedule_message_list_reflow()
        QTimer.singleShot(0, self._scroll_messages_to_bottom)

    def _flush_after_render_refresh(self) -> None:
        if not getattr(self, "_pending_after_render_refresh", False):
            return
        self._pending_after_render_refresh = False
        self.account_list.reload(self._filter_account_id)
        self._schedule_session_tree_refresh()

    def _clear_messages(self) -> None:
        if not self._ensure_message_area():
            return
        self._cancel_older_fetch()
        self.msg_list_view.clear_messages()
        self._msg_last_loaded_id = 0
        self._msg_last_loaded_session_id = None
        self._msg_page_offset = 0
        self._msg_has_more_older = False
        self._msg_loading_older = False
        self._msg_total_count = 0
        app = QApplication.instance()
        if app is not None:
            app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def _cancel_older_fetch(self) -> None:
        thread = getattr(self, "_older_fetch_thread", None)
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(100)
        self._older_fetch_thread = None
        if self._ensure_message_area():
            self.msg_list_view.set_loading_placeholder(False)

    def _on_msg_scroll_value_changed(self, value: int) -> None:
        if value > 12:
            return
        if getattr(self, "_msg_loading_older", False):
            return
        if not getattr(self, "_msg_has_more_older", False):
            return
        if getattr(self, "_render_in_progress", False):
            return
        if not self._current:
            return
        self._load_older_messages()

    def _load_older_messages(self) -> None:
        if not self._current or self._msg_loading_older or not self._msg_has_more_older:
            return
        if not self._ensure_message_area():
            return
        sid = int(self._current["session_id"])
        page_size = self._page_size()
        new_offset = max(0, self._msg_page_offset - page_size)
        if new_offset >= self._msg_page_offset:
            self._msg_has_more_older = False
            return
        limit = self._msg_page_offset - new_offset

        self._msg_loading_older = True
        self._older_scroll_before = (
            self.msg_list_view.verticalScrollBar().maximum(),
            self.msg_list_view.verticalScrollBar().value(),
        )
        self.msg_list_view.set_loading_placeholder(True)

        thread = _FetchOlderMessagesThread(sid, limit, new_offset)
        self._older_fetch_thread = thread
        thread.loaded.connect(self._on_older_messages_loaded)
        thread.failed.connect(self._on_older_messages_failed)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _on_older_messages_failed(self) -> None:
        self._msg_loading_older = False
        self._older_fetch_thread = None
        if self._ensure_message_area():
            self.msg_list_view.set_loading_placeholder(False)

    def _on_older_messages_loaded(self, rows: list, new_offset: int) -> None:
        self._msg_loading_older = False
        self._older_fetch_thread = None
        if not self._ensure_message_area():
            return
        self.msg_list_view.set_loading_placeholder(False)
        if not rows:
            self._msg_has_more_older = False
            return

        nick = (self._current or {}).get("buyer_nickname") or "买家"
        buyer_letter = avatar_letter(nick)
        msg_rows = [
            ChatMessageListModel.row_from_db(m, buyer_letter=buyer_letter) for m in rows
        ]
        before_max, before_value = getattr(
            self, "_older_scroll_before", (0, 0)
        )
        self.msg_list_view.prepend_messages(msg_rows)
        self._msg_page_offset = new_offset
        self._msg_has_more_older = new_offset > 0

        def _restore_scroll() -> None:
            bar = self.msg_list_view.verticalScrollBar()
            bar.setValue(before_value + (bar.maximum() - before_max))

        QTimer.singleShot(0, _restore_scroll)
        self.logger.debug(
            "加载更早消息 {} 条 session={} offset={}",
            len(rows),
            int(self._current["session_id"]),
            new_offset,
        )

    def _scroll_messages_to_bottom(self) -> None:
        view = getattr(self, "msg_list_view", None)
        if view is not None:
            view.scroll_to_bottom()

    def _cancel_message_render(self) -> None:
        self._render_token += 1
        self._msg_render_job = None

    def _messages_match_current_session(self) -> bool:
        if not self._current:
            return False
        sid = int(self._current["session_id"])
        return getattr(self, "_msg_last_loaded_session_id", None) == sid

    def _is_message_loading_visible(self) -> bool:
        bar = getattr(self, "_msg_loading_bar", None)
        return bar is not None and bar.isVisible()

    def _show_message_loading_early(self) -> None:
        now = time.monotonic()
        self._msg_loading_started_at = now
        self._msg_loading_hide_not_before = now + (T.MSG_LOADING_MIN_MS / 1000.0)
        bar = getattr(self, "_msg_loading_bar", None)
        if bar is not None:
            bar.setRange(0, 0)
            bar.show()
        if self._current:
            self.chat_sub.setText("正在加载聊天记录…")
            self.chat_sub.setStyleSheet(loading_subtitle_style())
        app = QApplication.instance()
        if app is not None:
            app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def _apply_loading_progress(self, current: int, total: int) -> None:
        total = max(1, int(total))
        current = min(max(0, int(current)), total)
        bar = getattr(self, "_msg_loading_bar", None)
        if bar is not None:
            bar.setRange(0, total)
            bar.setValue(current)
        pct = int(current * 100 / total) if total else 0
        if hasattr(self, "chat_sub") and self._current:
            self.chat_sub.setText(f"加载中 {pct}% · {current}/{total}")
            self.chat_sub.setStyleSheet(loading_subtitle_style())

    def _show_message_loading(self, total: int) -> None:
        total = max(1, int(total))
        self._msg_loading_total = total
        self._msg_loading_started_at = time.monotonic()
        self._apply_loading_progress(0, total)
        bar = getattr(self, "_msg_loading_bar", None)
        if bar is not None:
            bar.show()
        self.logger.info("消息加载 UI 显示: total={}", total)
        app = QApplication.instance()
        if app is not None:
            app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def _update_message_loading_progress(self, current: int, total: int) -> None:
        self._apply_loading_progress(current, total)
        bar = getattr(self, "_msg_loading_bar", None)
        if bar is not None and not bar.isVisible():
            bar.show()
        app = QApplication.instance()
        if app is not None:
            app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def _hide_message_loading(self) -> None:
        not_before = getattr(self, "_msg_loading_hide_not_before", 0.0)
        remain = not_before - time.monotonic()
        if remain > 0.05:
            QTimer.singleShot(int(remain * 1000), self._hide_message_loading_impl)
            return
        self._hide_message_loading_impl()

    def _hide_message_loading_impl(self) -> None:
        bar = getattr(self, "_msg_loading_bar", None)
        if bar is not None:
            bar.hide()
        if self._current:
            self._update_header_visuals()

    def _notify_message_load_success(self, total: int) -> None:
        if not self._current:
            return
        nick = self._current.get("buyer_nickname") or "买家"
        if total <= 0:
            content = f"{nick}：暂无历史消息"
        else:
            loaded = min(total, self._page_size())
            grand = int(getattr(self, "_msg_total_count", 0) or total)
            if grand > loaded:
                content = f"{nick}：已加载最近 {loaded} 条（共 {grand} 条，上滑加载更多）"
            else:
                content = f"{nick}：已加载 {loaded} 条聊天记录"
        InfoBar.success(
            title="加载完成",
            content=content,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2200,
            parent=self,
        )

    def _schedule_msg_render_tick(self, delay_ms: int = 0) -> None:
        token = self._render_token

        def _run() -> None:
            if token != self._render_token:
                return
            self._on_msg_render_tick()

        QTimer.singleShot(max(0, int(delay_ms)), _run)

    def _render_tick_reason(self, job: Optional[Dict[str, Any]]) -> str:
        if not job:
            return "no_job"
        if job.get("token") != self._render_token:
            return f"token_mismatch job={job.get('token')} cur={self._render_token}"
        if self._current:
            job_sid = int(job.get("session_id") or 0)
            cur_sid = int(self._current.get("session_id") or 0)
            if job_sid and cur_sid and job_sid != cur_sid:
                return f"session_mismatch job={job_sid} cur={cur_sid}"
        if not self._ensure_message_area():
            return "layout_unavailable"
        return "ok"

    def _on_msg_render_tick(self) -> None:
        job = getattr(self, "_msg_render_job", None)
        reason = self._render_tick_reason(job)
        if reason != "ok":
            self.logger.warning("消息渲染跳过: {}", reason)
            if reason in ("layout_unavailable",) or str(reason).startswith("session_mismatch"):
                self._render_in_progress = False
                self._msg_render_job = None
                self._hide_message_loading()
            return

        rows = job.get("rows") or []
        idx = int(job.get("index") or 0)
        total = int(job.get("total") or len(rows))
        buyer_letter = str(job.get("buyer_letter") or "买")
        end = min(idx + T.MSG_RENDER_BATCH, len(rows))

        batch_rows = [
            ChatMessageListModel.row_from_db(m, buyer_letter=buyer_letter)
            for m in rows[idx:end]
        ]
        self.msg_list_view.append_messages(batch_rows)

        if getattr(self, "_msg_render_job", None) is not job:
            return

        job["index"] = end
        self._update_message_loading_progress(end, total)
        if end <= T.MSG_RENDER_BATCH or end >= total or end % 20 == 0:
            self.logger.info("消息加载进度: {}/{}", end, total)

        if end >= len(rows):
            if rows and self._current:
                self._msg_last_loaded_id = int(rows[-1]["id"])
                self._msg_last_loaded_session_id = int(self._current["session_id"])
            self._msg_render_job = None
            self._finalize_message_render()
            return
        self._schedule_msg_render_tick(T.MSG_RENDER_INTERVAL_MS)

    def _finalize_message_render(self) -> None:
        self.msg_list_view.set_list_width(self._message_area_width())
        elapsed_ms = (time.monotonic() - self._msg_loading_started_at) * 1000.0
        remain_ms = max(0, int(T.MSG_LOADING_MIN_MS - elapsed_ms))
        QTimer.singleShot(remain_ms, self._complete_message_render)

    def _release_session_click_inflight(self) -> None:
        token = getattr(self, "_active_session_switch_token", None)
        if token is not None and token != getattr(self, "_session_switch_token", None):
            return
        self._session_click_inflight = False
        self._pending_session_click = None

    def _complete_message_render(self) -> None:
        if getattr(self, "_msg_render_job", None):
            return
        self._render_in_progress = False
        self._schedule_message_list_reflow()
        self._hide_message_loading()
        self._flush_after_render_refresh()
        self._scroll_messages_to_bottom()
        if self._msg_render_pending:
            self._msg_render_pending = False
            QTimer.singleShot(0, self._render_messages_from_db)
            return
        self._release_session_click_inflight()
        if getattr(self, "_msg_load_notify", False):
            self._msg_load_notify = False
            self._notify_message_load_success(int(getattr(self, "_msg_loading_total", 0)))

    def _render_messages_from_db(self) -> None:
        if not self._current:
            return
        sid = int(self._current["session_id"])
        if getattr(self, "_render_in_progress", False):
            self._cancel_message_render()
            self._cancel_older_fetch()
            self._render_in_progress = False
        render_token = self._render_token
        self._msg_render_pending = False
        self._render_in_progress = True

        page_size = self._page_size()
        total = db_manager.get_chat_message_count(sid)
        offset = max(0, total - page_size)
        rows = db_manager.get_chat_messages_paginated(sid, min(page_size, total), offset)
        self._msg_page_offset = offset
        self._msg_has_more_older = offset > 0
        self._msg_total_count = total
        nick = self._current.get("buyer_nickname") or "买家"
        buyer_letter = avatar_letter(nick)

        total = len(rows)
        if total == 0:
            self._msg_render_job = None
            self._render_in_progress = False
            self._clear_messages()
            self._release_session_click_inflight()
            QTimer.singleShot(0, self._hide_message_loading)
            QTimer.singleShot(0, self._flush_after_render_refresh)
            if getattr(self, "_msg_load_notify", False):
                self._msg_load_notify = False
                QTimer.singleShot(0, lambda: self._notify_message_load_success(0))
            return

        if not self._ensure_message_area():
            self.logger.error("消息区不可用，取消加载 session={}", sid)
            self._render_in_progress = False
            self._release_session_click_inflight()
            QTimer.singleShot(0, self._hide_message_loading)
            return

        self._show_message_loading(total)
        self._clear_messages()
        self._msg_render_job = {
            "session_id": sid,
            "rows": rows,
            "index": 0,
            "total": total,
            "buyer_letter": buyer_letter,
            "token": render_token,
        }
        self.logger.info(
            "消息加载开始: session={} total={} token={}", sid, total, render_token
        )
        self._schedule_msg_render_tick(0)

    def _can_incremental_message_update(self) -> bool:
        if not self._current or getattr(self, "_render_in_progress", False):
            return False
        sid = int(self._current["session_id"])
        if getattr(self, "_msg_last_loaded_session_id", None) != sid:
            return False
        return self._message_widget_count() > 0

    def _sync_incremental_messages(self, *, refresh_tree: bool = True) -> bool:
        if not self._can_incremental_message_update():
            return False
        if not self._ensure_message_area():
            return False
        sid = int(self._current["session_id"])
        after_id = int(getattr(self, "_msg_last_loaded_id", 0) or 0)
        rows = db_manager.get_chat_messages_after_id(sid, after_id)
        if not rows:
            return False

        nick = self._current.get("buyer_nickname") or "买家"
        buyer_letter = avatar_letter(nick)
        msg_rows = [
            ChatMessageListModel.row_from_db(m, buyer_letter=buyer_letter) for m in rows
        ]
        self.msg_list_view.append_messages(msg_rows)
        for m in rows:
            after_id = max(after_id, int(m["id"]))

        self._msg_last_loaded_id = after_id
        self._msg_last_loaded_session_id = sid
        self._schedule_message_list_reflow()
        self._scroll_messages_to_bottom()
        if refresh_tree:
            self._schedule_session_tree_refresh()
        self.logger.debug("增量载入 {} 条新消息 session={}", len(rows), sid)
        return True

    def _append_message_row(
        self,
        sender_type: str,
        content: str,
        t: Any,
        buyer_letter: str,
        content_type: Optional[str] = None,
        image_url: Optional[str] = None,
        is_read: bool = True,
        *,
        list_width: int = 0,
    ) -> None:
        if list_width:
            self.msg_list_view.set_list_width(list_width)
        row = ChatMessageRow(
            sender_type=sender_type,
            content=content,
            timestamp=t,
            buyer_letter=buyer_letter,
            content_type=content_type,
            image_url=image_url,
            is_read=is_read,
        )
        self.msg_list_view.append_messages([row])
