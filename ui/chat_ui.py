# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
实时聊天：三栏（账号 | 会话树 | 对话）。
深色色板，与 app.py 中 Fluent Theme.DARK 及界面原型一致。
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QEvent, Qt, QThread, QTimer, QSize
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QProgressBar,
)

from qfluentwidgets import (
    CaptionLabel,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SubtitleLabel,
    TreeWidget,
    FluentIcon as FIF,
)

from database.db_manager import db_manager
from database.chat_persist import set_active_chat_session
from config import get_config
from ui.conversation_hub import get_conversation_hub, make_account_key
from ui.widgets.account_group_list import AccountGroupList
from ui.widgets.chat_message_list_view import ChatMessageListView
from ui.chat.attachment_mixin import ChatAttachmentMixin
from ui.chat.message_list_mixin import ChatMessageListMixin
from ui.chat.send_workers import (
    AddressChangeExecuteThread,
    SendHumanMessageThread,
)
from ui.chat.session_tree import (
    apply_session_tree_item_visual,
    format_account_tree_label,
    format_session_tree_label,
    session_matches_filter,
    session_sort_key,
    unread_dot_icon,
)
from utils.logger_loguru import get_logger
from utils.qt_threading import run_on_main_thread

from ui.chat import tokens as T
from ui.chat.styles import (
    action_button_outline_style,
    build_live_chat_stylesheet,
    mode_toggle_button_styles,
)
from ui.chat.dialogs import avatar_letter


class ChatLiveWidget(ChatAttachmentMixin, ChatMessageListMixin, QFrame):
    """主导航「实时聊天」页面主体。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("ChatLive")
        self.setObjectName("LiveChatRoot")
        self._accounts: List[Dict[str, Any]] = []
        self._filter_account_id: Optional[int] = None
        self._session_filter: str = ""
        self._current: Optional[Dict[str, Any]] = None
        self._send_thread: Optional[SendHumanMessageThread] = None
        self._send_image_thread: Optional[SendImageMessageThread] = None
        self._send_goods_thread: Optional[SendGoodsCardThread] = None
        self._pending_text = ""

        self._hub = get_conversation_hub()
        self._hub.list_changed.connect(self._on_hub_list_changed)
        self._hub.message_logged.connect(self._on_hub_message_logged)

        self._hub_refresh_timer = QTimer(self)
        self._hub_refresh_timer.setSingleShot(True)
        self._hub_refresh_timer.timeout.connect(self._do_hub_list_refresh)

        self._tree_refresh_timer = QTimer(self)
        self._tree_refresh_timer.setSingleShot(True)
        self._tree_refresh_timer.timeout.connect(self._start_async_session_tree_refresh)
        self._tree_refresh_inflight = False
        self._tree_refresh_pending = False
        self._tree_refresh_after: Optional[Callable[[], None]] = None

        from core.chat_sync import ChatSyncService
        from config import get_config

        try:
            sync_ms = int(get_config("chat.mms_session_sync_interval_ms", 15000) or 15000)
        except (TypeError, ValueError):
            sync_ms = 15000
        self._sync = ChatSyncService(self, interval_ms=sync_ms)
        self._sync.tick.connect(self._on_sync_tick)
        self._sync.sync_finished.connect(self._on_mms_sync_finished)

        self._build_ui()
        self._apply_stylesheet()
        self._sync.start()

        from core.human_assist_bus import get_human_assist_bus

        self._human_bus = get_human_assist_bus(self)
        self._human_bus.buyer_conversation_ended.connect(
            self._on_buyer_conversation_ended,
            Qt.ConnectionType.QueuedConnection,
        )
        # assist_requested 由 main_ui.setup_human_assist_popup 统一挂接，避免延迟加载前无槽

        # 用于存储当前显示的人工协助弹窗
        self._current_assist_dialog = None
        
        # 输入框活动监控定时器 - 10 秒无输入自动切回 AI 模式
        self._input_activity_timer = QTimer(self)
        self._input_activity_timer.timeout.connect(self._on_input_activity_timeout)
        self._input_activity_timer.setSingleShot(True)
        
        # 为输入框安装事件过滤器，监控用户活动
        self.input_edit.installEventFilter(self)

        QTimer.singleShot(300, self._initial_load)

        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.timeout.connect(self._reflow_message_list)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._schedule_message_list_reflow()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._schedule_message_list_reflow()

    def eventFilter(self, obj, event):
        # 监控输入框的所有活动（按键、鼠标点击、焦点变化、文本变化等）
        if obj is self.input_edit:
            event_type = event.type()
            # 使用整数比较避免枚举值问题
            # KeyPress=6, FocusIn=8, FocusOut=9, MouseButtonPress=2, TextChange 用 QTextEdit 的信号
            if event_type in (
                QEvent.Type.KeyPress,
                QEvent.Type.FocusIn,
                QEvent.Type.MouseButtonPress,
            ) or (
                hasattr(QEvent.Type, "TextChange")
                and event_type == QEvent.Type.TextChange
            ):
                self._reset_input_activity_timer()
            
            # Enter 键直接发送消息
            if event.type() == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    # 如果按下 Shift+Enter，则换行
                    if event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
                        return False  # 让默认行为处理换行
                    # 否则发送消息
                    self._on_send()
                    return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        try:
            self._hub_refresh_timer.stop()
        except Exception:
            pass
        try:
            self._sync.stop()
            self._hub.list_changed.disconnect(self._on_hub_list_changed)
            self._hub.message_logged.disconnect(self._on_hub_message_logged)
            self._human_bus.buyer_conversation_ended.disconnect(self._on_buyer_conversation_ended)
        except (TypeError, RuntimeError) as e:
            self.logger.debug("closeEvent 断开 hub 信号: {}", e)
        try:
            self.input_edit.removeEventFilter(self)
        except Exception as e:
            self.logger.debug("closeEvent 移除 input 事件过滤: {}", e)
        set_active_chat_session(None, None)
        super().closeEvent(event)

    def _apply_stylesheet(self) -> None:
        self.setStyleSheet(build_live_chat_stylesheet())

    def _build_ui(self):
        """构建 UI（顶栏与关键词管理页：外边距 30、标题区 + 主内容间距 25）。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 16)
        layout.setSpacing(12)

        page_header = QWidget()
        ph = QHBoxLayout(page_header)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.setSpacing(20)
        title_area = QWidget()
        title_layout = QVBoxLayout(title_area)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(5)
        title_layout.addWidget(SubtitleLabel("实时聊天"))
        title_layout.addWidget(
            CaptionLabel("选择账号与会话，查看记录并人工回复买家")
        )
        self._ws_status_label = CaptionLabel("")
        self._ws_status_label.setWordWrap(True)
        title_layout.addWidget(self._ws_status_label)
        ph.addWidget(title_area)
        ph.addStretch()
        layout.addWidget(page_header)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        self.account_list = AccountGroupList(self)
        self.account_list.setObjectName("LiveChatAccountList")
        self.account_list.setMinimumWidth(200)
        self.account_list.setMaximumWidth(240)
        self.account_list.account_selected.connect(self._on_account_filter)

        mid_wrap = QFrame()
        mid_wrap.setObjectName("LiveChatSessionPanel")
        mid_l = QVBoxLayout(mid_wrap)
        mid_l.setContentsMargins(0, 0, 0, 0)
        mid_l.setSpacing(0)

        hdr = QFrame()
        hdr.setObjectName("LiveChatSessionHeader")
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(20, 16, 20, 16)
        hl.setSpacing(10)
        sec = CaptionLabel("会话列表")
        sec.setStyleSheet(f"color: {T.C_MUTED};")
        self.session_search = QLineEdit()
        self.session_search.setObjectName("LiveChatSessionSearch")
        self.session_search.setPlaceholderText("搜索客户或订单…")
        self.session_search.textChanged.connect(self._on_session_search_changed)
        _sp = self.session_search.palette()
        _sp.setColor(QPalette.ColorRole.PlaceholderText, QColor(T.C_DIM))
        self.session_search.setPalette(_sp)
        hl.addWidget(sec)
        hl.addWidget(self.session_search)
        mid_l.addWidget(hdr)

        self.session_tree = TreeWidget(self)
        self.session_tree.setObjectName("LiveChatSessionTree")
        self.session_tree.setHeaderHidden(True)
        self.session_tree.setIndentation(30)
        self.session_tree.setIconSize(QSize(24, 24))
        self.session_tree.setMinimumWidth(280)
        self.session_tree.setAnimated(True)
        self.session_tree.itemClicked.connect(self._on_session_clicked)
        mid_l.addWidget(self.session_tree, 1)

        right = QFrame()
        right.setObjectName("LiveChatRightPanel")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)

        top_bar = QFrame()
        top_bar.setObjectName("LiveChatTopBar")
        tb = QVBoxLayout(top_bar)
        tb.setContentsMargins(20, 10, 20, 12)
        tb.setSpacing(8)

        info = QHBoxLayout()
        info.setSpacing(12)
        self.lbl_avatar = QLabel("—")
        self.lbl_avatar.setObjectName("LiveChatAvatar")
        self.lbl_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_col = QVBoxLayout()
        name_col.setSpacing(4)
        self.chat_header = QLabel("未选择会话")
        self.chat_header.setObjectName("LiveChatNameLabel")
        self.chat_sub = QLabel("")
        self.chat_sub.setObjectName("LiveChatSubLabel")
        self.chat_sub.setWordWrap(True)
        name_col.addWidget(self.chat_header)
        name_col.addWidget(self.chat_sub)
        info.addWidget(self.lbl_avatar, 0, Qt.AlignmentFlag.AlignTop)
        info.addLayout(name_col, 1)

        self.btn_ai = PushButton(FIF.ROBOT, "AI 接待")
        self.btn_human = PushButton(FIF.PEOPLE, "人工接待")
        self.btn_close = PushButton(FIF.CLOSE, "结束会话")
        self.btn_ai.clicked.connect(self._on_toggle_ai_true)
        self.btn_human.clicked.connect(self._on_toggle_ai_false)
        self.btn_close.clicked.connect(self._on_close_session)
        for b in (self.btn_ai, self.btn_human):
            b.setObjectName("LiveChatModeButton")
            b.setMinimumWidth(112)
            b.setFixedHeight(36)
            b.setIconSize(QSize(16, 16))
        self.btn_close.setObjectName("LiveChatCloseButton")
        self.btn_close.setMinimumWidth(108)
        self.btn_close.setFixedHeight(36)
        self.btn_close.setIconSize(QSize(16, 16))

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(12)
        header_row.addLayout(info, 1)
        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(8)
        for b in (self.btn_ai, self.btn_human, self.btn_close):
            actions_row.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        header_row.addLayout(actions_row, 0)

        tb.addLayout(header_row, 0)
        self._msg_loading_bar = QProgressBar()
        self._msg_loading_bar.setObjectName("LiveChatLoadingBar")
        self._msg_loading_bar.setFixedHeight(3)
        self._msg_loading_bar.setTextVisible(False)
        self._msg_loading_bar.setRange(0, 100)
        self._msg_loading_bar.setValue(0)
        self._msg_loading_bar.hide()
        self._msg_loading_bar.setStyleSheet(
            f"""
            QProgressBar#LiveChatLoadingBar {{
                background-color: rgba(255, 255, 255, 0.06);
                border: none;
                border-radius: 2px;
                max-height: 3px;
                min-height: 3px;
            }}
            QProgressBar#LiveChatLoadingBar::chunk {{
                background-color: {T.C_LOADING};
                border-radius: 2px;
            }}
            """
        )
        tb.addWidget(self._msg_loading_bar)
        rv.addWidget(top_bar)

        self.msg_list_view = ChatMessageListView()
        self.msg_list_view.setObjectName("LiveChatMsgScroll")
        self.msg_list_view.setMinimumHeight(120)
        self.msg_list_view.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        # 兼容 mixin 内对滚动条的访问
        self.msg_scroll = self.msg_list_view

        self._msg_area = QWidget()
        self._msg_area.setObjectName("LiveChatMsgArea")
        msg_area_lay = QVBoxLayout(self._msg_area)
        msg_area_lay.setContentsMargins(0, 0, 0, 0)
        msg_area_lay.setSpacing(0)

        msg_area_lay.addWidget(self.msg_list_view, 1)

        self._msg_render_job: Optional[Dict[str, Any]] = None
        self._render_token = 0
        self._render_in_progress = False
        self._msg_loading_started_at = 0.0
        self._msg_loading_hide_not_before = 0.0
        self._msg_render_pending = False
        self._pending_after_render_refresh = False
        self._session_switch_token = 0
        self._active_session_switch_token = None
        self._session_click_inflight = False
        self._pending_session_click = None
        self._msg_load_notify = False
        self._msg_loading_total = 0
        self._msg_last_loaded_id = 0
        self._msg_last_loaded_session_id: Optional[int] = None
        self._msg_page_offset = 0
        self._msg_has_more_older = False
        self._msg_loading_older = False
        self._msg_total_count = 0

        self.msg_list_view.request_load_older.connect(self._load_older_messages)

        input_area = QFrame()
        input_area.setObjectName("LiveChatInputArea")
        input_area.setFrameShape(QFrame.Shape.NoFrame)
        input_area.setLineWidth(0)
        ia = QVBoxLayout(input_area)
        ia.setContentsMargins(20, 8, 20, 12)
        ia.setSpacing(8)

        qr_scroll = ScrollArea()
        qr_scroll.setObjectName("LiveChatQuickScroll")
        qr_scroll.setWidgetResizable(True)
        qr_scroll.setMaximumHeight(76)
        qr_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        qr_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        qr_scroll.setFrameShape(QFrame.Shape.NoFrame)
        qr_scroll.setLineWidth(0)
        qr_scroll.viewport().setAutoFillBackground(False)
        self.quick_wrap = QWidget()
        self.quick_wrap.setObjectName("LiveChatQuickStrip")
        self.quick_layout = QHBoxLayout(self.quick_wrap)
        self.quick_layout.setContentsMargins(0, 0, 0, 0)
        self.quick_layout.setSpacing(8)
        qr_scroll.setWidget(self.quick_wrap)

        tools_wrap = QWidget()
        tools_wrap.setObjectName("LiveChatToolsStrip")
        tools_wrap.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        tools_row = QHBoxLayout(tools_wrap)
        tools_row.setContentsMargins(0, 0, 0, 0)
        tools_row.setSpacing(8)
        
        # 文字按钮
        self.btn_emoji = PushButton("表情")
        self.btn_emoji.setToolTip("选择表情符号")
        self.btn_emoji.setFixedSize(60, 32)
        
        self.btn_img = PushButton("图片")
        self.btn_img.setToolTip("发送图片")
        self.btn_img.setFixedSize(60, 32)
        
        self.btn_ai_help = PushButton("AI 辅助")
        self.btn_ai_help.setToolTip("AI 辅助生成回复")
        self.btn_ai_help.setFixedSize(70, 32)
        self.btn_goods = PushButton("商品卡")
        self.btn_goods.setToolTip("一键发送商品卡")
        self.btn_goods.setFixedSize(70, 32)
        
        # 绑定点击事件
        self.btn_emoji.clicked.connect(self._on_emoji_clicked)
        self.btn_img.clicked.connect(self._on_img_clicked)
        self.btn_ai_help.clicked.connect(self._on_ai_help_clicked)
        self.btn_goods.clicked.connect(self._on_goods_card_clicked)
        
        tools_row.addWidget(self.btn_emoji)
        tools_row.addWidget(self.btn_img)
        tools_row.addWidget(self.btn_goods)
        tools_row.addWidget(self.btn_ai_help)
        tools_row.addStretch()

        self.input_edit = QTextEdit()
        self.input_edit.setObjectName("LiveChatInput")
        self.input_edit.setPlaceholderText("输入消息… (Ctrl+Enter 发送)")
        self.input_edit.setMinimumHeight(64)
        self.input_edit.setMaximumHeight(100)
        self.input_edit.setMinimumWidth(160)
        self.input_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.input_edit.installEventFilter(self)
        self.send_btn = PrimaryPushButton("发送")
        self.send_btn.setIcon(FIF.SEND)
        self.send_btn.setFixedSize(120, 40)
        self.send_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.send_btn.clicked.connect(self._on_send)

        inp_send_row = QHBoxLayout()
        inp_send_row.setSpacing(12)
        inp_send_row.addWidget(self.input_edit, 1)
        inp_send_row.addWidget(self.send_btn, 0, Qt.AlignmentFlag.AlignBottom)

        ia.addWidget(qr_scroll)
        ia.addWidget(tools_wrap)
        ia.addLayout(inp_send_row)
        rv.addWidget(self._msg_area, 1)
        rv.addWidget(input_area)

        split.addWidget(self.account_list)
        split.addWidget(mid_wrap)
        split.addWidget(right)
        split.setStretchFactor(2, 1)
        split.setSizes([210, 300, 920])
        layout.addWidget(split, 1)

        self._set_chat_enabled(False)
        self._style_action_buttons()

    def _mode_toggle_button_styles(self) -> tuple[str, str]:
        return mode_toggle_button_styles()

    def _update_mode_toggle_buttons(self) -> None:
        outline, primary = self._mode_toggle_button_styles()
        if not self._current:
            self.btn_ai.setStyleSheet(outline)
            self.btn_human.setStyleSheet(outline)
            return
        if bool(self._current.get("ai_mode", True)):
            self.btn_ai.setStyleSheet(primary)
            self.btn_human.setStyleSheet(outline)
        else:
            self.btn_ai.setStyleSheet(outline)
            self.btn_human.setStyleSheet(primary)

    def _style_action_buttons(self) -> None:
        self.btn_close.setStyleSheet(action_button_outline_style())
        self._update_mode_toggle_buttons()

    def _on_session_search_changed(self, text: str) -> None:
        self._session_filter = (text or "").strip().lower()
        self._schedule_session_tree_refresh()

    def _set_chat_enabled(self, on: bool):
        self.btn_ai.setEnabled(on and self._current is not None)
        self.btn_human.setEnabled(on and self._current is not None)
        self.btn_close.setEnabled(on and self._current is not None)
        # 三个工具按钮保持可点击；未选会话时在各自回调里给出提示。
        self.btn_img.setEnabled(True)
        self.btn_goods.setEnabled(True)
        self.btn_ai_help.setEnabled(True)
        self.input_edit.setEnabled(on)
        self.send_btn.setEnabled(on)

    def _update_header_visuals(self) -> None:
        if not self._current:
            self.lbl_avatar.setText("—")
            self.chat_header.setText("未选择会话")
            self.chat_sub.setText("")
            self.chat_header.setStyleSheet(f"color: {T.C_MUTED}; font-size: 16px; font-weight: 600;")
            self.chat_sub.setStyleSheet(f"color: {T.C_DIM}; font-size: 12px;")
            self._update_mode_toggle_buttons()
            return
        nick = self._current.get("buyer_nickname") or "买家"
        self.lbl_avatar.setText(avatar_letter(nick))
        self.chat_header.setText(nick)
        acc = self._current.get("account") or {}
        mode = "AI 自动接待" if self._current.get("ai_mode") else "人工接待中"
        shop = acc.get("shop_name") or ""
        self.chat_header.setStyleSheet(f"color: {T.C_TEXT}; font-size: 16px; font-weight: 600;")
        self.chat_sub.setText(f"● {mode}  ·  {shop}")
        self.chat_sub.setStyleSheet(f"color: {T.C_GREEN}; font-size: 12px;")
        self._update_mode_toggle_buttons()

    def _page_size(self) -> int:
        try:
            n = int(get_config("chat.ui_page_size", T.DEFAULT_PAGE_SIZE) or T.DEFAULT_PAGE_SIZE)
            return max(1, min(n, 500))
        except (TypeError, ValueError):
            return T.DEFAULT_PAGE_SIZE

    def _initial_load(self):
        self._accounts = db_manager.list_all_accounts_for_chat()
        for acc in self._accounts:
            key = make_account_key(
                acc["channel_name"], acc["platform_shop_id"], acc["username"]
            )
            self._hub.sync_latest_conversations(key, int(acc["id"]))
        self.account_list.reload()
        self._refresh_session_trees()
        self._rebuild_quick_replies()
        self._refresh_ws_status_hint()
        try:
            self._sync.schedule_sync_all()
        except Exception as e:
            self.logger.debug("初始 MMS 会话同步调度失败: {}", e)

    def _refresh_ws_status_hint(self) -> None:
        """提示 WebSocket 是否在收消息（与「开始回复」绑定，非仅上线）。"""
        label = getattr(self, "_ws_status_label", None)
        if label is None:
            return
        try:
            from core.channel_facade import list_connected_accounts
            from ui.auto_reply_ui import auto_reply_manager

            connected = list_connected_accounts()
            running = auto_reply_manager.get_running_count()
            if connected:
                names = "、".join(s.username for s in connected[:3])
                extra = f" 等{len(connected)}个" if len(connected) > 3 else ""
                try:
                    from config import get_config

                    mms_sync = bool(get_config("chat.mms_session_sync_enabled", False))
                except Exception:
                    mms_sync = False
                if mms_sync:
                    sync_hint = (
                        "软件会从 MMS 同步会话列表（只读，不改变网页分配）；"
                        "AI 回复仍依赖 WebSocket。"
                    )
                else:
                    sync_hint = (
                        "会话列表以 WebSocket 实时推送为准；"
                        "浏览器与软件同时在线时，网页可能抢 WebSocket（auth fail）。"
                    )
                label.setText(f"消息通道：已连接 {names}{extra}。{sync_hint}")
                label.setStyleSheet(f"color: {T.SUCCESS};")
            elif running > 0:
                label.setText(
                    "消息通道：正在连接 WebSocket… 若长时间无会话，请在「自动回复」确认已点「开始回复」。"
                )
                label.setStyleSheet(f"color: {T.WARNING};")
            else:
                label.setText(
                    "消息通道：未连接。请在「自动回复」对接待账号点「上线」→「开始回复」；"
                    "仅上线不会收到买家消息。转接须转到本软件正在监听的那个子账号。"
                )
                label.setStyleSheet(f"color: {T.ERROR};")
        except Exception as e:
            self.logger.debug("WS 状态提示刷新失败: {}", e)

    def _reload_accounts_from_db(self) -> None:
        """从数据库刷新账号列表，避免「已上线/已连接」仍显示离线。"""
        self._accounts = db_manager.list_all_accounts_for_chat()

    def _account_status_text(self, acc: Dict[str, Any]) -> str:
        """展示用接待状态：WebSocket 已连接优先，其次读 DB accounts.status。"""
        shop_id = str(acc.get("platform_shop_id") or "")
        user_id = str(acc.get("seller_user_id") or "")
        try:
            from core.channel_facade import account_display_status

            ws_status = account_display_status(shop_id, user_id)
            if ws_status:
                return ws_status
        except Exception as e:
            self.logger.debug("读取 WS 连接状态失败: {}", e)
        code = acc.get("status")
        if code == 1:
            return "在线"
        if code == 3:
            return "离线"
        if code == 0:
            return "休息"
        return "未验证"

    def _on_sync_tick(self):
        """周期同步：MMS 会话列表（后台）+ 连接状态提示；不在此阻塞 UI 做结案/刷树。"""
        self._refresh_ws_status_hint()
        try:
            self._sync.schedule_sync_all()
        except Exception as e:
            self.logger.debug(f"同步钩子跳过: {e}")

    def _on_mms_sync_finished(self, _count: int) -> None:
        self.account_list.reload(self._filter_account_id)
        self._schedule_session_tree_refresh()

    def _on_hub_list_changed(self, _account_key: str):
        try:
            debounce_ms = int(get_config("ui.hub_list_refresh_debounce_ms", 300) or 300)
        except (TypeError, ValueError):
            debounce_ms = 300
        debounce_ms = max(50, min(debounce_ms, 2000))
        self._hub_refresh_timer.start(debounce_ms)

    def _do_hub_list_refresh(self):
        self.account_list.reload(self._filter_account_id)
        self._schedule_session_tree_refresh()

    def _on_hub_message_logged(
        self, account_key: str, customer_uid: str, role: str, text: str, ts: float
    ):
        if not self._current:
            return
        acc = self._current.get("account")
        if not acc:
            return
        key = make_account_key(
            acc["channel_name"], acc["platform_shop_id"], acc["username"]
        )
        if key != account_key or str(customer_uid) != str(self._current.get("buyer_uid")):
            return
        if getattr(self, "_msg_render_job", None):
            self._msg_render_pending = True
            return
        if self._is_message_loading_visible():
            self._msg_render_pending = True
            return
        if self._sync_incremental_messages():
            return
        self._render_messages_from_db()

    def _on_account_filter(self, account_id):
        self._filter_account_id = account_id

        def after() -> None:
            if account_id is not None or self._current is None:
                self._auto_open_first_session()

        self._schedule_session_tree_refresh(after=after)

    def _auto_open_first_session(self) -> None:
        """打开当前筛选下第一个会话（未读优先，其次最近消息）。"""
        best: Optional[tuple] = None
        for i in range(self.session_tree.topLevelItemCount()):
            parent = self.session_tree.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                cd = child.data(0, Qt.ItemDataRole.UserRole)
                if not isinstance(cd, dict) or cd.get("type") != "session":
                    continue
                s = cd["session"]
                key = session_sort_key(s)
                if best is None or key > best[0]:
                    best = (key, child)
        if best is None:
            return
        child = best[1]
        self.session_tree.setCurrentItem(child)
        self.session_tree.scrollToItem(child)
        self._on_session_clicked(child, 0)

    def _session_matches_filter(self, s: Dict[str, Any]) -> bool:
        return session_matches_filter(s, self._session_filter)

    def _tree_refresh_debounce_ms(self) -> int:
        try:
            ms = int(get_config("ui.session_tree_refresh_debounce_ms", 200) or 200)
        except (TypeError, ValueError):
            ms = 200
        return max(0, min(ms, 2000))

    def _schedule_session_tree_refresh(
        self,
        delay_ms: Optional[int] = None,
        *,
        after: Optional[Callable[[], None]] = None,
    ) -> None:
        if after is not None:
            prev = self._tree_refresh_after
            if prev is None:
                self._tree_refresh_after = after
            else:
                self._tree_refresh_after = lambda p=prev, n=after: (p(), n())
        if delay_ms is None:
            delay_ms = self._tree_refresh_debounce_ms()
        if delay_ms <= 0:
            self._start_async_session_tree_refresh()
        else:
            self._tree_refresh_timer.start(delay_ms)

    def _start_async_session_tree_refresh(self) -> None:
        if self._tree_refresh_inflight:
            self._tree_refresh_pending = True
            return
        self._tree_refresh_inflight = True
        filter_account_id = self._filter_account_id
        session_filter = self._session_filter

        def work() -> None:
            payload: Optional[Dict[str, Any]] = None
            try:
                accounts = db_manager.list_all_accounts_for_chat()
                all_sessions = db_manager.get_chat_sessions(None, None)
                by_account: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
                for s in all_sessions:
                    aid = int(s.get("account_id") or 0)
                    if aid:
                        by_account[aid].append(s)
                payload = {
                    "accounts": accounts,
                    "sessions_by_account": dict(by_account),
                    "filter_account_id": filter_account_id,
                    "session_filter": session_filter,
                }
            except Exception as e:
                self.logger.error("后台加载会话树失败: {}", e)

            def apply() -> None:
                self._tree_refresh_inflight = False
                if payload is not None:
                    self._apply_session_tree_payload(payload)
                cb = self._tree_refresh_after
                self._tree_refresh_after = None
                if cb is not None:
                    try:
                        cb()
                    except Exception as e:
                        self.logger.debug("会话树刷新回调失败: {}", e)
                if self._tree_refresh_pending:
                    self._tree_refresh_pending = False
                    self._schedule_session_tree_refresh(0)

            run_on_main_thread(apply)

        threading.Thread(target=work, daemon=True).start()

    def _apply_session_tree_payload(self, payload: Dict[str, Any]) -> None:
        self._accounts = payload["accounts"]
        filter_account_id = payload["filter_account_id"]
        session_filter = str(payload.get("session_filter") or "")
        keep_sid: Optional[int] = None
        keep_aid: Optional[int] = None
        if self._current:
            try:
                keep_sid = int(self._current.get("session_id", 0))
                keep_aid = int(self._current.get("account", {}).get("id", 0))
            except (TypeError, ValueError):
                keep_sid = None
                keep_aid = None
        sessions_by_account: Dict[int, List[Dict[str, Any]]] = payload.get(
            "sessions_by_account", {}
        )
        restore_item: Optional[QTreeWidgetItem] = None
        self.session_tree.clear()
        accounts = (
            [a for a in self._accounts if a["id"] == filter_account_id]
            if filter_account_id is not None
            else self._accounts
        )
        for acc in accounts:
            sessions_all = sessions_by_account.get(int(acc["id"]), [])
            unread = sum(int(s.get("unread_count") or 0) for s in sessions_all)
            st_txt = self._account_status_text(acc)
            parent = QTreeWidgetItem(
                [format_account_tree_label(acc, st_txt, unread)]
            )
            parent.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {"type": "account", "account": acc},
            )
            parent.setSizeHint(0, QSize(0, 54))
            if unread > 0:
                parent.setIcon(0, unread_dot_icon())
            self.session_tree.addTopLevelItem(parent)
            sessions = sorted(
                sessions_all,
                key=session_sort_key,
                reverse=True,
            )
            for s in sessions:
                if not session_matches_filter(s, session_filter):
                    continue
                child = QTreeWidgetItem([format_session_tree_label(s)])
                child.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    {"type": "session", "session": s, "account": acc},
                )
                child.setSizeHint(0, QSize(0, 50))
                apply_session_tree_item_visual(child, s)
                parent.addChild(child)
                if (
                    restore_item is None
                    and keep_sid is not None
                    and keep_aid is not None
                    and int(s["id"]) == keep_sid
                    and int(acc["id"]) == keep_aid
                ):
                    restore_item = child
            parent.setExpanded(True)
        if restore_item is not None:
            self.session_tree.setCurrentItem(restore_item)
            self.session_tree.scrollToItem(restore_item)

    def _refresh_session_trees(self) -> None:
        """兼容入口：调度后台刷新，避免主线程阻塞。"""
        self._schedule_session_tree_refresh(0)

    def apply_human_escalation(self, payload: dict) -> None:
        """弹窗后跳转：聚焦接待账号与买家，并载入库内全部聊天记录。"""
        try:
            aid = int(payload["account_id"])
        except (TypeError, ValueError, KeyError):
            return
        acc = db_manager.get_account_row_by_id(aid)
        if not acc:
            self.logger.warning("apply_human_escalation: 账号不存在")
            return
        self._accounts = db_manager.list_all_accounts_for_chat()
        self._filter_account_id = aid
        self.account_list.reload(aid)
        db_manager.get_or_create_chat_session(
            account_id=aid,
            platform_shop_id=str(payload["platform_shop_id"]),
            account_name=str(payload["login_username"]),
            buyer_uid=str(payload["buyer_uid"]),
            buyer_nickname=str(payload.get("buyer_nickname") or "买家"),
        )
        sess = db_manager.get_chat_session_by_buyer(aid, str(payload["buyer_uid"]), "active")
        if not sess:
            self.logger.warning("apply_human_escalation: 未找到会话")
            return
        self._current = {
            "session_id": sess["id"],
            "buyer_uid": sess["buyer_uid"],
            "buyer_nickname": sess.get("buyer_nickname") or "买家",
            "account": acc,
            "ai_mode": bool(sess.get("ai_mode", False)),
        }
        set_active_chat_session(aid, str(sess["buyer_uid"]))
        db_manager.mark_chat_messages_read(int(sess["id"]))
        self._update_header_visuals()
        self._set_chat_enabled(True)
        self._rebuild_quick_replies(aid)
        self._msg_load_notify = True
        self._render_messages_from_db()
        self._select_tree_session_for_buyer(aid, str(payload["buyer_uid"]))
        try:
            self._hub.total_unread_changed.emit(db_manager.get_total_unread_chat())
        except Exception as e:
            self.logger.debug("total_unread_changed emit: {}", e)

    def _select_tree_session_for_buyer(self, account_id: int, buyer_uid: str) -> None:
        def after() -> None:
            for i in range(self.session_tree.topLevelItemCount()):
                parent = self.session_tree.topLevelItem(i)
                data = parent.data(0, Qt.ItemDataRole.UserRole)
                if not isinstance(data, dict) or data.get("type") != "account":
                    continue
                if int(data["account"]["id"]) != int(account_id):
                    continue
                for j in range(parent.childCount()):
                    child = parent.child(j)
                    cd = child.data(0, Qt.ItemDataRole.UserRole)
                    if not isinstance(cd, dict) or cd.get("type") != "session":
                        continue
                    if str(cd["session"].get("buyer_uid")) == str(buyer_uid):
                        self.session_tree.setCurrentItem(child)
                        self.session_tree.scrollToItem(child)
                        return

        self._schedule_session_tree_refresh(0, after=after)

    def _on_human_assist_requested(self, payload: dict) -> None:
        """人工协助请求 - 显示弹窗并跳转到实时聊天"""
        try:
            # 提取信息
            account_id = int(payload.get("account_id", 0))
            buyer_uid = str(payload.get("buyer_uid", ""))
            buyer_nickname = str(payload.get("buyer_nickname", "买家"))
            account_name = str(payload.get("login_username", ""))
            question = str(payload.get("summary") or payload.get("question", ""))
            reason = str(payload.get("reason", "转人工"))
            shop_name = str(payload.get("shop_name", ""))
            
            self.logger.info(f"人工协助请求：account={account_id}, buyer={buyer_uid}, reason={reason}")
            
            # 关闭之前的弹窗（如果存在）
            if self._current_assist_dialog and self._current_assist_dialog.isVisible():
                self.logger.info("关闭之前的弹窗")
                self._current_assist_dialog.close()
            
            # 创建并显示新的人工协助弹窗
            from ui.widgets.human_assist_dialog import HumanAssistDialog
            
            self.logger.info("开始创建 HumanAssistDialog")
            self._current_assist_dialog = HumanAssistDialog(payload, self)
            self._current_assist_dialog.go_to_chat_requested.connect(self._on_go_to_chat_requested)
            self._current_assist_dialog.confirm_address_change_requested.connect(
                self._on_confirm_address_change_requested
            )
            
            self.logger.info(f"弹窗已创建，准备显示。父窗口：{self}")
            self._current_assist_dialog.show()
            self.logger.info(f"弹窗已调用 show()，visible={self._current_assist_dialog.isVisible()}")
            
            # 同时显示 InfoBar 通知（作为额外提醒）
            bar_title = "🔔 买家申请转人工"
            if reason == "ai_after_sales_pm":
                bar_title = "🔔 AI 回复需产品经理跟进"
            elif reason == "after_sales_policy":
                bar_title = "🔔 售后需人工处理"
            elif reason == "order_address_change":
                bar_title = "🔔 买家申请改地址"
            elif reason == "buyer_emotion_alert":
                bar_title = "⚠️ 买家情绪波动预警"
            elif reason == "buyer_emotion_escalate":
                bar_title = "⚠️ 买家情绪波动（已转人工）"
            InfoBar.warning(
                title=bar_title,
                content=f"买家：{buyer_nickname}\n问题：{question[:50]}",
                parent=self,
                duration=3000,
                position=InfoBarPosition.TOP,
            )
            
        except Exception as e:
            self.logger.error(f"处理人工协助请求失败：{e}", exc_info=True)
    
    def _on_go_to_chat_requested(self, payload: dict) -> None:
        """处理跳转对话窗口的请求 - 强制从任何页面切换到实时聊天"""
        try:
            account_id = int(payload.get("account_id", 0))
            buyer_uid = str(payload.get("buyer_uid", ""))
            buyer_nickname = str(payload.get("buyer_nickname", "买家"))

            self.logger.info(
                f"🚨 开始强制跳转到会话：{buyer_nickname}, account_id={account_id}"
            )

            from utils.window_focus import (
                restore_application_window,
                switch_main_window_to_widget,
            )

            parent_window = self.window()
            restore_application_window(parent_window)

            if parent_window and switch_main_window_to_widget(parent_window, self):
                self.logger.info("✅ 已恢复主窗口并切换到实时聊天页面")
                QTimer.singleShot(
                    500,
                    lambda: self._find_and_select_session_with_focus(
                        account_id, buyer_uid, buyer_nickname
                    ),
                )
                return

            self.logger.warning("未切换到实时聊天页，仍尝试选中会话")
            QTimer.singleShot(
                200,
                lambda: self._find_and_select_session(
                    account_id, buyer_uid, buyer_nickname
                ),
            )

        except Exception as e:
            self.logger.error(f"跳转对话窗口失败：{e}", exc_info=True)

    def _on_confirm_address_change_requested(self, payload: dict) -> None:
        """店主确认改址：后台调 MMS + 自动回复买家。"""
        order_sn = str(payload.get("order_sn") or "")
        buyer_uid = str(payload.get("buyer_uid") or "")
        self.logger.info(f"确认改址：order={order_sn}, buyer={buyer_uid}")

        thread = AddressChangeExecuteThread(payload)
        thread.finished_with_result.connect(
            lambda ok, msg, err: self._on_address_change_execute_finished(
                ok, msg, err, payload
            )
        )
        thread.start()

    def _on_address_change_execute_finished(
        self,
        ok: bool,
        msg: str,
        err: str,
        payload: dict,
    ) -> None:
        buyer_nickname = str(payload.get("buyer_nickname") or "买家")
        order_sn = str(payload.get("order_sn") or "")
        if ok:
            InfoBar.success(
                title="改址已提交",
                content=f"订单 {order_sn} 地址修改成功",
                parent=self,
                duration=4000,
                position=InfoBarPosition.TOP,
            )
            return

        detail = err or "改址失败"
        InfoBar.error(
            title="改址失败",
            content=f"买家 {buyer_nickname}：{detail[:80]}",
            parent=self,
            duration=5000,
            position=InfoBarPosition.TOP,
        )
        out = dict(payload)
        out["focus_topic"] = "address_change"
        self._on_go_to_chat_requested(out)
    
    def _find_and_select_session_with_focus(self, account_id: int, buyer_uid: str, buyer_nickname: str) -> None:
        """查找并选中会话，同时确保窗口获得焦点"""
        try:
            from utils.window_focus import restore_application_window

            parent_window = self.window()
            restore_application_window(parent_window)
            
            # 查找并选中会话
            self._find_and_select_session(account_id, buyer_uid, buyer_nickname)
            
        except Exception as e:
            self.logger.error(f"_find_and_select_session_with_focus 失败：{e}", exc_info=True)
    
    def _find_and_select_session(self, account_id: int, buyer_uid: str, buyer_nickname: str) -> None:
        """查找并选中指定会话"""
        try:
            def after() -> None:
                for i in range(self.session_tree.topLevelItemCount()):
                    parent = self.session_tree.topLevelItem(i)
                    data = parent.data(0, Qt.ItemDataRole.UserRole)
                    if not isinstance(data, dict) or data.get("type") != "account":
                        continue
                    if int(data["account"]["id"]) != account_id:
                        continue
                    for j in range(parent.childCount()):
                        child = parent.child(j)
                        cd = child.data(0, Qt.ItemDataRole.UserRole)
                        if not isinstance(cd, dict) or cd.get("type") != "session":
                            continue
                        if str(cd["session"].get("buyer_uid")) == buyer_uid:
                            self.session_tree.setCurrentItem(child)
                            self.session_tree.scrollToItem(child)
                            self._on_session_clicked(child, 0)
                            self.logger.info(f"✅ 已跳转到会话：{buyer_nickname}")
                            return
                self.logger.warning(
                    f"未找到对应的会话：account_id={account_id}, buyer_uid={buyer_uid}"
                )

            self._schedule_session_tree_refresh(0, after=after)
        except Exception as e:
            self.logger.error(f"查找会话失败：{e}", exc_info=True)

    def _on_buyer_conversation_ended(self, payload: dict) -> None:
        try:
            aid = int(payload["account_id"])
            buid = str(payload["buyer_uid"])
        except (TypeError, ValueError, KeyError):
            return
        acc_row = db_manager.get_account_row_by_id(aid)
        if acc_row:
            key = make_account_key(
                acc_row["channel_name"],
                str(acc_row["platform_shop_id"]),
                acc_row["username"],
            )
            self._hub.clear_conversation(key, buid)
        db_manager.delete_chat_session_by_buyer(aid, buid)
        cur = self._current
        if cur and int(cur["account"]["id"]) == aid and str(cur.get("buyer_uid")) == buid:
            self._current = None
            set_active_chat_session(None, None)
            self._clear_messages()
            self._set_chat_enabled(False)
            self._update_header_visuals()
        self._refresh_session_trees()
        self.account_list.reload(self._filter_account_id)
        try:
            self._hub.total_unread_changed.emit(db_manager.get_total_unread_chat())
        except Exception as e:
            self.logger.debug("total_unread_changed emit (buyer ended): {}", e)

    def _restore_ai_for_current_if_manual(self) -> None:
        """
        人工退出当前会话时，自动切回 AI 模式。
        这样买家后续再次发消息会继续由 AI 接待。
        """
        if not self._current:
            return
        if self._current.get("ai_mode", True):
            return
        sid = int(self._current["session_id"])
        from database.session_store import set_ai_mode

        set_ai_mode(sid, True)
        self._current["ai_mode"] = True
        self._update_header_visuals()
        self.logger.info("会话已自动切回 AI 接待模式（离开聊天窗口）")
        self._show_ai_mode_notice("检测到您已离开聊天窗口，已自动切换为 AI 接待")
    
    def _reset_input_activity_timer(self) -> None:
        """人工接待时：重置 10 秒无输入自动切回 AI 的倒计时。"""
        if not self._current or self._current.get("ai_mode", True):
            return
        if self._input_activity_timer.isActive():
            self._input_activity_timer.stop()
        self._input_activity_timer.start(10000)
        self.logger.debug("输入框活动检测到，重置 10 秒定时器")

    def _on_input_activity_timeout(self) -> None:
        """输入框 10 秒无活动，自动切回 AI 模式"""
        if not self._current:
            return
        if self._current.get("ai_mode", True):
            return  # 本来就是 AI 模式，不需要切换
        sid = int(self._current["session_id"])
        from database.session_store import set_ai_mode

        set_ai_mode(sid, True)
        self._current["ai_mode"] = True
        self._update_header_visuals()
        self.logger.info("会话已自动切回 AI 接待模式（输入框 10 秒无活动）")
        self._show_ai_mode_notice("输入框 10 秒无活动，已自动切换为 AI 接待")
    
    def _show_ai_mode_notice(self, message: str) -> None:
        """显示 AI 模式切换提示"""
        InfoBar.info(
            title="接待模式",
            content=message,
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self,
        )

    def _on_session_clicked(self, item: QTreeWidgetItem, _col: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        if data.get("type") == "account":
            parent = item
            if parent.isExpanded():
                parent.setExpanded(False)
                return
            parent.setExpanded(True)
            pick: Optional[QTreeWidgetItem] = None
            best_key: Optional[tuple] = None
            for j in range(parent.childCount()):
                child = parent.child(j)
                cd = child.data(0, Qt.ItemDataRole.UserRole)
                if not isinstance(cd, dict) or cd.get("type") != "session":
                    continue
                s = cd["session"]
                key = session_sort_key(s)
                if best_key is None or key > best_key:
                    best_key = key
                    pick = child
            if pick is not None:
                self.session_tree.setCurrentItem(pick)
                self._on_session_clicked(pick, 0)
            return
        if data.get("type") != "session":
            return
        s = data["session"]
        if getattr(self, "_session_click_inflight", False):
            pending = getattr(self, "_pending_session_click", None)
            try:
                clicked_sid = int(s.get("id") or 0)
            except (TypeError, ValueError):
                clicked_sid = 0
            if (
                isinstance(pending, dict)
                and int(pending.get("session_id") or 0) == clicked_sid
            ):
                return
        fresh = db_manager.get_chat_session_by_id(int(s["id"]))
        if fresh:
            s = fresh
        acc = data["account"]
        session_id = int(s["id"])
        if str(s.get("status") or "active") == "closed":
            db_manager.reopen_chat_session(session_id)
            reopened = db_manager.get_chat_session_by_id(session_id)
            if reopened:
                s = reopened
        messages_ready = self._messages_match_current_session()
        was_same_session = (
            self._current is not None
            and int(self._current.get("session_id", 0)) == session_id
            and messages_ready
        )
        needs_reload = (
            not was_same_session
            or getattr(self, "_render_in_progress", False)
            or not messages_ready
        )
        # 切换到其它买家前，若当前会话在人工模式则自动切回 AI
        if self._current and int(self._current.get("session_id", 0)) != session_id:
            self._restore_ai_for_current_if_manual()
        self._session_switch_token += 1
        switch_token = self._session_switch_token
        self._pending_session_click = {"session_id": session_id, "token": switch_token}
        self._session_click_inflight = True
        self._tree_refresh_timer.stop()
        if needs_reload:
            self._cancel_message_render()
            self._cancel_older_fetch()
        self._current = {
            "session_id": s["id"],
            "buyer_uid": s["buyer_uid"],
            "buyer_nickname": s.get("buyer_nickname") or "买家",
            "account": acc,
            "ai_mode": s.get("ai_mode", True),
        }
        set_active_chat_session(int(acc["id"]), str(s["buyer_uid"]))
        from database.session_store import mark_session_read, load_session_summary

        mark_session_read(session_id)
        fresh_summary = load_session_summary(session_id)
        if fresh_summary:
            s = {
                **s,
                "ai_mode": fresh_summary.ai_mode,
                "unread_count": fresh_summary.unread_count,
            }
        self._update_header_visuals()
        if not self._current.get("ai_mode", True):
            self._reset_input_activity_timer()
        self._set_chat_enabled(True)
        if needs_reload:
            self._rebuild_quick_replies(int(acc["id"]))
        if not needs_reload:
            self._session_click_inflight = False
            self._pending_session_click = None
            try:
                self._hub.total_unread_changed.emit(db_manager.get_total_unread_chat())
            except Exception as e:
                self.logger.debug("total_unread_changed emit (session reselect): {}", e)
            return
        self._msg_load_notify = True
        self._show_message_loading_early()
        self._pending_after_render_refresh = True
        self._active_session_switch_token = switch_token
        self._render_messages_from_db()
        try:
            self._hub.total_unread_changed.emit(db_manager.get_total_unread_chat())
        except Exception as e:
            self.logger.debug("total_unread_changed emit (session click): {}", e)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._message_widget_count() > 0:
            self._schedule_message_list_reflow()

    def _rebuild_quick_replies(self, account_id: Optional[int] = None):
        while self.quick_layout.count():
            w = self.quick_layout.takeAt(0).widget()
            if w:
                w.deleteLater()
        aid = account_id
        if aid is None and self._current:
            aid = int(self._current["account"]["id"])
        reps = db_manager.get_quick_replies(aid)
        for r in reps[:12]:
            title = r.get("title") or r.get("category") or "快捷"
            btn = PushButton(title)
            btn.setProperty("qr_content", r.get("content", ""))
            btn.setProperty("qr_id", r.get("id"))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(self._on_quick_reply_click)
            self.quick_layout.addWidget(btn)
        self.quick_layout.addStretch()

    def _on_quick_reply_click(self):
        btn = self.sender()
        if not btn:
            return
        content = btn.property("qr_content") or ""
        rid = btn.property("qr_id")
        self.input_edit.setPlainText(self.input_edit.toPlainText() + str(content))
        try:
            if rid is not None and str(rid).isdigit():
                db_manager.bump_quick_reply_usage(int(rid))
        except (TypeError, ValueError):
            pass

    def _on_toggle_ai_true(self):
        self._set_ai_mode(True)

    def _on_toggle_ai_false(self):
        self._set_ai_mode(False)

    def _set_ai_mode(self, ai: bool):
        if not self._current:
            return
        sid = int(self._current["session_id"])
        from database.session_store import set_ai_mode

        set_ai_mode(sid, ai)
        self._current["ai_mode"] = ai
        self._update_header_visuals()
        if ai:
            if self._input_activity_timer.isActive():
                self._input_activity_timer.stop()
        else:
            # 切到人工后：10 秒内输入框无活动则自动切回 AI
            self._reset_input_activity_timer()
        self.logger.info("会话 AI 模式已切换: session_id={} ai_mode={}", sid, ai)
        tip = "已切换为 AI 自动接待，买家新消息将由 AI 回复。" if ai else "已切换为人工接待，AI 将不自动回复买家。"
        InfoBar.success(
            title="接待模式",
            content=tip,
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=2500,
            parent=self,
        )

    def _on_close_session(self):
        if not self._current:
            return
        # 人工退出聊天界面时，不关闭会话，只切回 AI 模式
        self._restore_ai_for_current_if_manual()
        self._current = None
        set_active_chat_session(None, None)
        self._clear_messages()
        self._set_chat_enabled(False)
        self._update_header_visuals()
        self._refresh_session_trees()
        self.account_list.reload(self._filter_account_id)

    def _on_send(self):
        if not self._current:
            return
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        if self._send_thread and self._send_thread.isRunning():
            return
        acc = self._current["account"]
        self._pending_text = text
        self.send_btn.setEnabled(False)
        self._send_thread = SendHumanMessageThread(
            str(acc["platform_shop_id"]),
            str(acc["seller_user_id"]),
            str(self._current["buyer_uid"]),
            text,
            login_username=str(acc.get("username") or ""),
            channel_name=str(acc.get("channel_name") or "pinduoduo"),
            session_id=self._current.get("session_id"),
        )
        self._send_thread.finished_with_result.connect(self._on_send_done)
        self._send_thread.start()

    def _on_send_done(self, ok: bool, err: str):
        self.send_btn.setEnabled(True)
        if not ok:
            self.input_edit.setPlainText(self._pending_text)
            QMessageBox.warning(self, "发送失败", err or "")
            return
        if not self._current:
            return
        acc = self._current["account"]
        get_conversation_hub().record_manual_sent(
            acc["channel_name"],
            str(acc["platform_shop_id"]),
            acc["username"],
            str(self._current["buyer_uid"]),
            self._pending_text,
            str(acc["seller_user_id"]),
        )
        try:
            from Message.handlers.ai_reply_watchdog import notify_outbound_reply

            notify_outbound_reply(
                metadata={
                    "channel_name": acc.get("channel_name", "pinduoduo"),
                    "shop_id": str(acc["platform_shop_id"]),
                    "user_id": str(acc["seller_user_id"]),
                    "from_uid": str(self._current["buyer_uid"]),
                }
            )
        except Exception as e:
            self.logger.debug("watchdog notify_outbound_reply: {}", e)
        self.input_edit.clear()
        QTimer.singleShot(80, self._sync_incremental_messages)
