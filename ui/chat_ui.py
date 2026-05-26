"""
实时聊天：三栏（账号 | 会话树 | 对话）。
深色色板，与 app.py 中 Fluent Theme.DARK 及界面原型一致。
"""
from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QEvent, Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QInputDialog,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QGridLayout,
    QPushButton,
    QScrollArea,
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
from ui.conversation_hub import get_conversation_hub, make_account_key
from ui.widgets.account_group_list import AccountGroupList
from ui import apple_ui_tokens as UI
from utils.chat_message_html import format_chat_bubble_html
from utils.logger_loguru import get_logger

# 人工协助会话打开时一次性载入历史条数上限
_CHAT_HISTORY_LIMIT = 100_000

# 与 apple_ui_tokens / Apple 深色规范一致（聊天区 HTML 与顶栏）
_C_BG = UI.BG_PRIMARY
_C_PANEL = UI.BG_SECONDARY
_C_CARD = UI.BG_SECONDARY
_C_BORDER = UI.BORDER
_C_TEXT = UI.TEXT_PRIMARY
_C_MUTED = UI.TEXT_SECONDARY
_C_DIM = UI.TEXT_TERTIARY
_C_ACCENT = UI.ACCENT
_C_GREEN = UI.SUCCESS
_C_AI_BUBBLE = "#1D2D46"
_C_MSG_BODY = "#E6EAF2"

# 气泡常量定义
_B_BUBBLE_RADIUS = "18px"
_B_BUBBLE_TAIL_RADIUS = "8px"
_B_SYSTEM_RADIUS = "14px"
_C_BUBBLE_FRAME_SELF = "#2C2C2E"
_C_SYSTEM_BG = "#2C2C2E"
_C_SYSTEM_TEXT = "#98989D"
_C_TIME_TEXT = "#E5E5EA"
# 输入区底为 _C_PANEL；快捷语 / 工具条 / 输入框用略亮一层，避免与背景「糊成一片」
_C_CHROME_BG = UI.BG_TERTIARY
_C_CHROME_HOVER = "#48484A"
_C_CHROME_BORDER = "rgba(255, 255, 255, 0.22)"
_C_CHROME_PRESSED = "#3D3D40"


class SendHumanMessageThread(QThread):
    finished_with_result = pyqtSignal(bool, str)

    def __init__(self, shop_id: str, user_id: str, recipient_uid: str, text: str):
        super().__init__()
        self.shop_id = shop_id
        self.user_id = user_id
        self.recipient_uid = recipient_uid
        self.text = text

    def run(self):
        try:
            from Channel.pinduoduo.utils.API.send_message import SendMessage

            sender = SendMessage(self.shop_id, self.user_id)
            result = sender.send_text(self.recipient_uid, self.text)
            if isinstance(result, dict) and result.get("success"):
                self.finished_with_result.emit(True, "")
                return
            if isinstance(result, str) and result:
                self.finished_with_result.emit(False, result)
                return
            self.finished_with_result.emit(False, "发送失败")
        except Exception as e:
            self.finished_with_result.emit(False, str(e))


class SendImageMessageThread(QThread):
    finished_with_result = pyqtSignal(bool, str)

    def __init__(self, shop_id: str, user_id: str, recipient_uid: str, image_url: str):
        super().__init__()
        self.shop_id = shop_id
        self.user_id = user_id
        self.recipient_uid = recipient_uid
        self.image_url = image_url

    def run(self):
        try:
            from Channel.pinduoduo.utils.API.send_message import SendMessage

            sender = SendMessage(self.shop_id, self.user_id)
            result = sender.send_image(self.recipient_uid, self.image_url)
            if isinstance(result, dict) and result.get("success"):
                self.finished_with_result.emit(True, "")
                return
            err = ""
            if isinstance(result, dict):
                err = str(result.get("error_msg") or result.get("error") or "")
            self.finished_with_result.emit(False, err or "图片发送失败")
        except Exception as e:
            self.finished_with_result.emit(False, str(e))


class SendGoodsCardThread(QThread):
    finished_with_result = pyqtSignal(bool, str)

    def __init__(self, shop_id: str, user_id: str, recipient_uid: str, goods_id: int):
        super().__init__()
        self.shop_id = shop_id
        self.user_id = user_id
        self.recipient_uid = recipient_uid
        self.goods_id = goods_id

    def run(self):
        try:
            from Channel.pinduoduo.utils.API.send_message import SendMessage

            sender = SendMessage(self.shop_id, self.user_id)
            result = sender.send_mallGoodsCard(self.recipient_uid, self.goods_id, biz_type=2)
            if isinstance(result, dict) and result.get("success"):
                self.finished_with_result.emit(True, "")
                return
            err = ""
            if isinstance(result, dict):
                err = str(result.get("error_msg") or result.get("error") or "")
            self.finished_with_result.emit(False, err or "商品卡发送失败")
        except Exception as e:
            self.finished_with_result.emit(False, str(e))


def _avatar_letter(name: str, fallback: str = "?") -> str:
    s = (name or "").strip()
    if not s:
        return fallback
    return s[0].upper() if s.isascii() and len(s) == 1 else s[0]


class GoodsIdInputDialog(QDialog):
    """商品 ID 输入对话框（支持 12 位，禁止粘贴）"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("发送商品卡")
        self.setFixedSize(400, 200)
        
        # 布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)
        
        # 说明文字
        info_label = QLabel("请输入商品 ID（goods_id）\n支持 12 位数字，禁止粘贴")
        info_label.setStyleSheet("color: #8E8E93; font-size: 13px;")
        layout.addWidget(info_label)
        
        # 输入框
        self.input = QLineEdit()
        self.input.setPlaceholderText("请输入 12 位商品 ID")
        self.input.setMaxLength(12)  # 最多 12 位
        self.input.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                font-size: 16px;
                border: 2px solid #007AFF;
                border-radius: 8px;
            }
            QLineEdit:focus {
                border: 2px solid #0055CC;
            }
        """)
        # 禁用粘贴
        self.input.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        layout.addWidget(self.input)
        
        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def get_goods_id(self) -> int:
        """获取输入的商品 ID"""
        text = self.input.text().strip()
        try:
            return int(text)
        except (ValueError, TypeError):
            return 0


class EmojiPickerDialog(QDialog):
    """图片网格表情选择器"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择表情")
        self.setFixedSize(520, 420)
        
        # 布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # 表情网格
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # 表情容器
        emoji_widget = QWidget()
        emoji_layout = QGridLayout(emoji_widget)
        emoji_layout.setContentsMargins(10, 10, 10, 10)
        emoji_layout.setSpacing(8)
        
        # 精选表情（按截图中的常见表情）
        self.emojis = [
            # 第 1 行
            "😊", "😂", "😍", "", "😘", "😜", "😝", "😛",
            # 第 2 行
            "😅", "😆", "😁", "🙂", "🙃", "😉", "😌", "",
            # 第 3 行
            "😒", "😞", "😔", "😟", "😕", "🙁", "☹️", "😣",
            # 第 4 行
            "😖", "😫", "😩", "😤", "😠", "😡", "😶", "😐",
            # 第 5 行
            "😑", "😬", "🙄", "😯", "😦", "😧", "😨", "😰",
            # 第 6 行
            "😥", "😓", "🤗", "🤔", "🤐", "🤓", "", "😝",
            # 第 7 行
            "🤑", "🤒", "🤕", "😷", "🤢", "", "🤧", "😇",
            # 第 8 行
            "🤠", "🤡", "", "🤫", "🤭", "🧐", "", "😈",
            # 常用符号
            "👍", "👎", "👌", "✌️", "🤞", "🤟", "🤘", "👋",
            "👏", "", "💪", "🤝", "❤️", "💔", "💕", "💖",
            "🎉", "✨", "🔥", "🌟", "💯", "💐", "🌹", "🎁",
        ]
        
        # 创建表情按钮
        row = 0
        col = 0
        cols_per_row = 8
        
        for emoji in self.emojis:
            btn = QPushButton(emoji)
            btn.setFixedSize(44, 44)
            btn.setStyleSheet("""
                QPushButton {
                    font-size: 28px;
                    background-color: transparent;
                    border: 2px solid transparent;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background-color: #F0F0F0;
                    border: 2px solid #007AFF;
                }
                QPushButton:pressed {
                    background-color: #E0E0E0;
                }
            """)
            btn.clicked.connect(lambda checked, e=emoji: self._on_emoji_selected(e))
            emoji_layout.addWidget(btn, row, col)
            
            col += 1
            if col >= cols_per_row:
                col = 0
                row += 1
        
        scroll.setWidget(emoji_widget)
        layout.addWidget(scroll)
        
        # 常用表情栏
        favorites_layout = QHBoxLayout()
        favorites_layout.setSpacing(8)
        
        search_label = QLabel("🔍")
        search_label.setStyleSheet("font-size: 20px;")
        favorites_layout.addWidget(search_label)
        
        for fav in ["😊", "😂", "❤️", "👍", "🎉", "🔥"]:
            btn = QPushButton(fav)
            btn.setFixedSize(36, 36)
            btn.setStyleSheet("""
                QPushButton {
                    font-size: 24px;
                    background-color: transparent;
                    border: none;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background-color: #F0F0F0;
                }
            """)
            btn.clicked.connect(lambda checked, e=fav: self._on_emoji_selected(e))
            favorites_layout.addWidget(btn)
        
        favorites_layout.addStretch()
        layout.addLayout(favorites_layout)
    
    def _on_emoji_selected(self, emoji: str):
        """表情被选中"""
        self.selected_emoji = emoji
        self.accept()
    
    def exec(self) -> str:
        """执行对话框并返回选中的表情"""
        self.selected_emoji = None
        super().exec()
        return self.selected_emoji


class ChatLiveWidget(QFrame):
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

        from core.chat_sync import ChatSyncService

        self._sync = ChatSyncService(self, interval_ms=10000)
        self._sync.tick.connect(self._on_sync_tick)

        self._build_ui()
        self._apply_stylesheet()
        self._sync.start()

        from core.human_assist_bus import get_human_assist_bus

        self._human_bus = get_human_assist_bus(self)
        self._human_bus.buyer_conversation_ended.connect(self._on_buyer_conversation_ended)
        self._human_bus.assist_requested.connect(self._on_human_assist_requested)
        
        # 用于存储当前显示的人工协助弹窗
        self._current_assist_dialog = None
        
        # 输入框活动监控定时器 - 10 秒无输入自动切回 AI 模式
        self._input_activity_timer = QTimer(self)
        self._input_activity_timer.timeout.connect(self._on_input_activity_timeout)
        self._input_activity_timer.setSingleShot(True)
        
        # 为输入框安装事件过滤器，监控用户活动
        self.input_edit.installEventFilter(self)

        QTimer.singleShot(300, self._initial_load)

    def eventFilter(self, obj, event):
        # 监控输入框的所有活动（按键、鼠标点击、焦点变化、文本变化等）
        if obj is self.input_edit:
            event_type = event.type()
            # 使用整数比较避免枚举值问题
            # KeyPress=6, FocusIn=8, FocusOut=9, MouseButtonPress=2, TextChange 用 QTextEdit 的信号
            if event_type in (QEvent.Type.KeyPress, QEvent.Type.FocusIn, 
                             QEvent.Type.MouseButtonPress) or \
               (hasattr(QEvent.Type, 'TextChange') and event_type == QEvent.Type.TextChange):
                # 重置定时器 - 用户有活动
                if self._input_activity_timer.isActive():
                    self._input_activity_timer.stop()
                self._input_activity_timer.start(10000)  # 10 秒超时
                self.logger.debug("输入框活动检测到，重置 10 秒定时器")
            
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
            self._sync.stop()
            self._hub.list_changed.disconnect(self._on_hub_list_changed)
            self._hub.message_logged.disconnect(self._on_hub_message_logged)
            self._human_bus.buyer_conversation_ended.disconnect(self._on_buyer_conversation_ended)
        except TypeError as e:
            self.logger.debug("closeEvent 断开 hub 信号: {}", e)
        try:
            self.input_edit.removeEventFilter(self)
        except Exception as e:
            self.logger.debug("closeEvent 移除 input 事件过滤: {}", e)
        set_active_chat_session(None, None)
        super().closeEvent(event)

    def _apply_stylesheet(self) -> None:
        self.setStyleSheet(
            f"""
            #LiveChatRoot {{
                background-color: {_C_BG};
                border: none;
            }}
            #LiveChatSessionPanel {{
                background-color: {_C_PANEL};
                border: none;
            }}
            #LiveChatSessionHeader {{
                background-color: {_C_PANEL};
                border-bottom: 1px solid {_C_BORDER};
            }}
            #LiveChatSessionSearch {{
                background-color: {_C_CARD};
                border: 1px solid {_C_BORDER};
                border-radius: 12px;
                padding: 8px 12px;
                color: {_C_TEXT};
                font-size: 14px;
            }}
            #LiveChatSessionSearch:focus {{
                border: 1px solid {_C_ACCENT};
            }}
            #LiveChatAccountList {{
                background-color: {_C_BG};
                color: {_C_MUTED};
                border: none;
                border-right: 1px solid {_C_BORDER};
                font-size: 13px;
                outline: none;
            }}
            #LiveChatAccountList::item {{
                padding: 12px 14px;
                border-radius: 10px;
                margin: 2px 6px;
                color: {_C_MUTED};
            }}
            #LiveChatAccountList::item:hover {{
                background-color: {_C_CARD};
                color: {_C_TEXT};
            }}
            #LiveChatAccountList::item:selected {{
                background-color: {_C_CARD};
                color: {_C_ACCENT};
                font-weight: 500;
            }}
            QTreeWidget#LiveChatSessionTree {{
                background-color: {_C_PANEL};
                color: {_C_TEXT};
                border: none;
                outline: none;
                font-size: 13px;
            }}
            QTreeWidget#LiveChatSessionTree::item {{
                padding: 8px 6px;
                border-radius: 10px;
                min-height: 36px;
            }}
            QTreeWidget#LiveChatSessionTree::item:hover {{
                background-color: #23293A;
            }}
            QTreeWidget#LiveChatSessionTree::item:selected {{
                background-color: {_C_BORDER};
                border-left: 3px solid {_C_ACCENT};
            }}
            QTreeWidget#LiveChatSessionTree::branch:has-siblings:!adjoins-item {{
                border-image: none;
            }}
            
            /* 消息气泡样式 */
            QWidget#ChatPlainCol {{
                background-color: {_C_CARD};
                border: 1px solid {_C_BORDER};
                border-radius: {_B_BUBBLE_RADIUS};
                border-bottom-left-radius: {_B_BUBBLE_TAIL_RADIUS};
            }}
            QWidget#ChatPlainColSystem {{
                background-color: {_C_SYSTEM_BG};
                border: 1px solid {_C_BORDER};
                border-radius: {_B_SYSTEM_RADIUS};
            }}
            QWidget#ChatPlainColSelf {{
                background-color: {_C_ACCENT};
                border: 1px solid {_C_BUBBLE_FRAME_SELF};
                border-radius: {_B_BUBBLE_RADIUS};
                border-bottom-right-radius: {_B_BUBBLE_TAIL_RADIUS};
            }}
            
            #LiveChatRightPanel {{
                background-color: {_C_BG};
                border: none;
            }}
            #LiveChatTopBar {{
                background-color: {_C_BG};
                border-bottom: 1px solid {_C_BORDER};
            }}
            #LiveChatAvatar {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #FF6B6B, stop:1 #FF8E8E);
                color: #FFFFFF;
                font-weight: bold;
                font-size: 16px;
                border-radius: 12px;
                min-width: 40px;
                max-width: 40px;
                min-height: 40px;
                max-height: 40px;
            }}
            #LiveChatNameLabel {{
                color: {_C_TEXT};
                font-size: 16px;
                font-weight: 600;
            }}
            #LiveChatSubLabel {{
                font-size: 12px;
            }}
            #LiveChatMsgBrowser {{
                background-color: {_C_BG};
                color: {_C_MSG_BODY};
                border: none;
                padding: 12px 16px;
                font-size: 14px;
            }}
            #LiveChatInputArea {{
                background-color: {_C_BG};
                border: none;
            }}
            #LiveChatInput {{
                background-color: {_C_CHROME_BG};
                border: 1px solid {_C_CHROME_BORDER};
                border-radius: 12px;
                padding: 12px;
                color: {_C_TEXT};
                font-size: 14px;
                outline: none;
            }}
            #LiveChatInput:focus {{
                border: 1px solid {_C_ACCENT};
            }}
            QScrollArea#LiveChatTopBarActionsScroll {{
                background: transparent;
                border: none;
            }}
            QScrollArea#LiveChatTopBarActionsScroll > QWidget {{
                background: transparent;
                border: none;
            }}
            QScrollArea#LiveChatQuickScroll {{
                background: transparent;
                border: none;
            }}
            QScrollArea#LiveChatQuickScroll > QWidget {{
                background: transparent;
                border: none;
            }}
            #LiveChatQuickStrip {{
                background: transparent;
                border: none;
            }}
            #LiveChatToolsStrip PushButton {{
                background-color: {_C_CHROME_BG};
                color: {_C_TEXT};
                border: 1px solid {_C_CHROME_BORDER};
                border-radius: 8px;
                font-size: 12px;
                padding: 4px 8px;
            }}
            #LiveChatToolsStrip PushButton:hover {{
                background-color: {_C_CHROME_HOVER};
                border-color: rgba(10, 132, 255, 0.55);
            }}
            #LiveChatToolsStrip PushButton:pressed {{
                background-color: {_C_CHROME_PRESSED};
            }}
            #LiveChatToolsStrip PushButton:disabled {{
                background-color: {_C_PANEL};
                color: {_C_DIM};
                border-color: {_C_BORDER};
            }}
            #LiveChatQuickStrip PushButton {{
                background-color: {_C_CHROME_BG};
                color: {_C_TEXT};
                border: 1px solid {_C_CHROME_BORDER};
                border-radius: 14px;
                font-size: 12px;
                padding: 6px 14px;
            }}
            #LiveChatQuickStrip PushButton:hover {{
                background-color: {_C_CHROME_HOVER};
                border-color: {_C_ACCENT};
                color: {_C_TEXT};
            }}
            #LiveChatQuickStrip PushButton:pressed {{
                background-color: {_C_CHROME_PRESSED};
            }}
            """
        )

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
        sec.setStyleSheet(f"color: {_C_MUTED};")
        self.session_search = QLineEdit()
        self.session_search.setObjectName("LiveChatSessionSearch")
        self.session_search.setPlaceholderText("搜索客户或订单…")
        self.session_search.textChanged.connect(self._on_session_search_changed)
        _sp = self.session_search.palette()
        _sp.setColor(QPalette.ColorRole.PlaceholderText, QColor(_C_DIM))
        self.session_search.setPalette(_sp)
        hl.addWidget(sec)
        hl.addWidget(self.session_search)
        mid_l.addWidget(hdr)

        self.session_tree = TreeWidget(self)
        self.session_tree.setObjectName("LiveChatSessionTree")
        self.session_tree.setHeaderHidden(True)
        self.session_tree.setIndentation(14)
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

        self.btn_profile = PushButton("📋 资料")
        self.btn_profile.setEnabled(False)
        self.btn_profile.setToolTip("后续版本开放")
        self.btn_ai = PushButton("🤖 转 AI")
        self.btn_human = PushButton("👤 人工接待")
        self.btn_close = PushButton("结束会话")
        self.btn_ai.clicked.connect(self._on_toggle_ai_true)
        self.btn_human.clicked.connect(self._on_toggle_ai_false)
        self.btn_close.clicked.connect(self._on_close_session)
        for b in (self.btn_profile, self.btn_ai, self.btn_human, self.btn_close):
            b.setFixedHeight(40)
            b.setSizePolicy(
                QSizePolicy.Policy.Minimum,
                QSizePolicy.Policy.Fixed,
            )

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(0)
        actions_row.addStretch(1)
        hdr_actions_inner = QWidget()
        hdr_actions_inner.setObjectName("LiveChatTopBarActions")
        hdr_actions_inner.setFixedHeight(40)
        hdr_act_layout = QHBoxLayout(hdr_actions_inner)
        hdr_act_layout.setContentsMargins(0, 0, 0, 0)
        hdr_act_layout.setSpacing(8)
        for b in (self.btn_profile, self.btn_ai, self.btn_human, self.btn_close):
            hdr_act_layout.addWidget(b)

        hdr_act_scroll = ScrollArea()
        hdr_act_scroll.setObjectName("LiveChatTopBarActionsScroll")
        hdr_act_scroll.setWidgetResizable(False)
        hdr_act_scroll.setFixedHeight(44)
        hdr_act_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        hdr_act_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        hdr_act_scroll.setFrameShape(QFrame.Shape.NoFrame)
        hdr_act_scroll.setLineWidth(0)
        hdr_act_scroll.viewport().setAutoFillBackground(False)
        hdr_act_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        hdr_act_scroll.setWidget(hdr_actions_inner)
        actions_row.addWidget(hdr_act_scroll, 1)

        tb.addLayout(info, 0)
        tb.addLayout(actions_row, 0)
        rv.addWidget(top_bar)

        self.browser = QTextBrowser()
        self.browser.setObjectName("LiveChatMsgBrowser")
        self.browser.setOpenExternalLinks(False)
        self.browser.setMinimumHeight(120)
        self.browser.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

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
        rv.addWidget(self.browser, 1)
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
        """(描边, 主色高亮) — 用于「转 AI / 人工接待」与当前 ai_mode 同步。"""
        outline = (
            f"PushButton {{ padding: 8px 14px; border-radius: 10px; border: 1px solid {_C_BORDER};"
            f" background: transparent; color: {_C_MUTED}; font-size: 13px; }}"
            f"PushButton:hover {{ background-color: {_C_CARD}; color: {_C_TEXT}; }}"
            f"PushButton:disabled {{ color: {_C_DIM}; border-color: {_C_BORDER}; }}"
        )
        primary = (
            f"PushButton {{ padding: 8px 14px; border-radius: 10px; border: 1px solid {_C_ACCENT};"
            f" background: {_C_ACCENT}; color: #FFFFFF; font-size: 13px; font-weight: 600; }}"
            f"PushButton:hover {{ background-color: #0077ED; border-color: #0077ED; }}"
            f"PushButton:disabled {{ background: {_C_BORDER}; color: {_C_DIM}; border-color: {_C_BORDER}; }}"
        )
        return outline, primary

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
        outline = (
            f"PushButton {{ padding: 8px 14px; border-radius: 10px; border: 1px solid {_C_BORDER};"
            f" background: transparent; color: {_C_MUTED}; font-size: 13px; }}"
            f"PushButton:hover {{ background-color: {_C_CARD}; color: {_C_TEXT}; }}"
        )
        self.btn_profile.setStyleSheet(outline)
        self.btn_close.setStyleSheet(outline)
        self._update_mode_toggle_buttons()

    def _on_session_search_changed(self, text: str) -> None:
        self._session_filter = (text or "").strip().lower()
        self._refresh_session_trees()

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
            self.chat_header.setStyleSheet(f"color: {_C_MUTED}; font-size: 16px; font-weight: 600;")
            self.chat_sub.setStyleSheet(f"color: {_C_DIM}; font-size: 12px;")
            self._update_mode_toggle_buttons()
            return
        nick = self._current.get("buyer_nickname") or "买家"
        self.lbl_avatar.setText(_avatar_letter(nick))
        self.chat_header.setText(nick)
        acc = self._current.get("account") or {}
        mode = "AI 自动接待" if self._current.get("ai_mode") else "人工接待中"
        shop = acc.get("shop_name") or ""
        self.chat_header.setStyleSheet(f"color: {_C_TEXT}; font-size: 16px; font-weight: 600;")
        self.chat_sub.setText(f"● {mode}  ·  {shop}")
        self.chat_sub.setStyleSheet(f"color: {_C_GREEN}; font-size: 12px;")
        self._update_mode_toggle_buttons()

    def _initial_load(self):
        self._accounts = db_manager.list_all_accounts_for_chat()
        self.account_list.reload()
        self._refresh_session_trees()
        self._rebuild_quick_replies()

    def _on_sync_tick(self):
        """周期同步钩子：预留平台历史拉取，再刷新会话树。"""
        try:
            if self._filter_account_id:
                self._sync.sync_messages(int(self._filter_account_id))
        except Exception as e:
            self.logger.debug(f"同步钩子跳过: {e}")
        self._refresh_session_trees()

    def _on_hub_list_changed(self, _account_key: str):
        self.account_list.reload()
        self._refresh_session_trees()
    
    def _on_emoji_clicked(self) -> None:
        """表情按钮点击 - 打开图片网格表情选择器。"""
        self.logger.info("表情按钮被点击")
        
        # 创建表情选择对话框
        dialog = EmojiPickerDialog(self)
        emoji = dialog.exec()
        
        if emoji:
            # 插入表情到输入框
            cursor = self.input_edit.textCursor()
            cursor.insertText(emoji)
            self.input_edit.setFocus()

    def _on_img_clicked(self):
        """图片按钮点击：支持本地图片（预留上传）与 URL 两种方式。"""
        if not self._current:
            QMessageBox.warning(self, "无会话", "请先选择一个会话")
            return

        chooser = QMessageBox(self)
        chooser.setWindowTitle("发送图片")
        chooser.setText("请选择发送方式：")
        local_btn = chooser.addButton("本地图片", QMessageBox.ButtonRole.AcceptRole)
        url_btn = chooser.addButton("图片 URL", QMessageBox.ButtonRole.ActionRole)
        chooser.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        chooser.setDefaultButton(local_btn)
        chooser.exec()

        clicked = chooser.clickedButton()
        if clicked is local_btn:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "选择本地图片",
                "",
                "Images (*.png *.jpg *.jpeg *.gif *.webp *.bmp)",
            )
            if not file_path:
                return
            self._send_local_image(file_path)
            return
        if clicked is url_btn:
            self._prompt_and_send_image_url()

    def _prompt_and_send_image_url(self, default_url: str = "https://") -> None:
        url, ok = QInputDialog.getText(
            self,
            "发送图片",
            "请输入可公网访问的图片 URL：",
            QLineEdit.EchoMode.Normal,
            default_url,
        )
        if not ok:
            return
        image_url = (url or "").strip()
        if not image_url.startswith(("http://", "https://")):
            QMessageBox.warning(self, "图片地址无效", "请输入 http/https 开头的图片 URL")
            return
        self._send_image_via_url(image_url)

    def _send_local_image(self, file_path: str) -> None:
        """发送本地图片：先走上传适配器，失败后可回退 URL 发送。"""
        acc = self._current["account"]
        try:
            from Channel.pinduoduo.utils.API.upload_media import MediaUploader

            uploader = MediaUploader(str(acc["platform_shop_id"]), str(acc["seller_user_id"]))
            result = uploader.upload_local_image(file_path)
            if result.get("success") and result.get("image_url"):
                self._send_image_via_url(str(result["image_url"]))
                return
            err = str(result.get("error_msg") or "图片上传失败")
        except Exception as e:
            err = str(e)

        fallback = QMessageBox.question(
            self,
            "本地图片上传未就绪",
            f"{err}\n\n是否改为手动输入图片 URL 发送？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if fallback == QMessageBox.StandardButton.Yes:
            self._prompt_and_send_image_url(default_url="https://")

    def _send_image_via_url(self, image_url: str) -> None:
        if not self._current:
            return

        acc = self._current["account"]
        self.btn_img.setEnabled(False)
        self._send_image_thread = SendImageMessageThread(
            str(acc["platform_shop_id"]),
            str(acc["seller_user_id"]),
            str(self._current["buyer_uid"]),
            image_url,
        )
        self._send_image_thread.finished_with_result.connect(self._on_image_send_done)
        self._send_image_thread.start()

    def _on_image_send_done(self, ok: bool, err: str) -> None:
        self.btn_img.setEnabled(True)
        if not ok:
            QMessageBox.warning(self, "图片发送失败", err or "")
            return
        QMessageBox.information(self, "发送成功", "图片已发送")

    def _on_goods_card_clicked(self) -> None:
        """人工一键发送商品卡。"""
        if not self._current:
            QMessageBox.warning(self, "无会话", "请先选择一个会话")
            return

        # 使用自定义对话框，支持 12 位商品 ID 且禁止粘贴
        dialog = GoodsIdInputDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        
        goods_id = dialog.get_goods_id()
        if goods_id <= 0:
            QMessageBox.warning(self, "输入错误", "请输入有效的商品 ID（1-12 位数字）")
            return

        acc = self._current["account"]
        self.btn_goods.setEnabled(False)
        self._send_goods_thread = SendGoodsCardThread(
            str(acc["platform_shop_id"]),
            str(acc["seller_user_id"]),
            str(self._current["buyer_uid"]),
            int(goods_id),
        )
        self._send_goods_thread.finished_with_result.connect(self._on_goods_send_done)
        self._send_goods_thread.start()

    def _on_goods_send_done(self, ok: bool, err: str) -> None:
        self.btn_goods.setEnabled(True)
        if not ok:
            QMessageBox.warning(self, "商品卡发送失败", err or "")
            return
        QMessageBox.information(self, "发送成功", "商品卡已发送")

    def _on_ai_help_clicked(self):
        """AI 助手按钮点击 - AI 辅助生成回复"""
        self.logger.info("AI 助手按钮被点击")
        
        # 检查是否有当前会话
        if not self._current:
            QMessageBox.warning(
                self,
                "无会话",
                "请先选择一个会话",
            )
            return
        
        # 获取最近的客户消息
        last_message = self._current.get("last_message", "")
        if not last_message:
            last_message = "客户消息"
        
        # 显示 AI 辅助对话框
        reply, ok = QInputDialog.getText(
            self,
            "AI 辅助回复",
            f"客户消息：{last_message}\n\n请输入或修改回复内容：",
            QLineEdit.EchoMode.Normal,
            "您好，感谢您的咨询！"
        )
        
        if ok and reply:
            # 插入回复到输入框
            self.input_edit.clear()
            self.input_edit.insertPlainText(reply)
            self.input_edit.setFocus()

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
        self._render_messages_from_db()

    def _on_account_filter(self, account_id):
        self._filter_account_id = account_id
        self._refresh_session_trees()

    def _session_matches_filter(self, s: Dict[str, Any]) -> bool:
        if not self._session_filter:
            return True
        q = self._session_filter
        nick = (s.get("buyer_nickname") or "").lower()
        prev = (s.get("last_message") or "").lower()
        buid = str(s.get("buyer_uid") or "").lower()
        return q in nick or q in prev or q in buid

    def _refresh_session_trees(self):
        self.session_tree.clear()
        accounts = (
            [a for a in self._accounts if a["id"] == self._filter_account_id]
            if self._filter_account_id is not None
            else self._accounts
        )
        for acc in accounts:
            unread = sum(
                s.get("unread_count", 0)
                for s in db_manager.get_chat_sessions(acc["id"], "active")
            )
            st = acc.get("status")
            st_txt = "在线" if st == 1 else ("离线" if st == 3 else "休息")
            parent = QTreeWidgetItem(
                [f"{acc.get('shop_name','')} · {acc.get('username','')}  ({st_txt})  未读 {unread}"]
            )
            parent.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {"type": "account", "account": acc},
            )
            parent.setFlags(parent.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.session_tree.addTopLevelItem(parent)
            sessions = db_manager.get_chat_sessions(acc["id"], "active")
            for s in sessions:
                if not self._session_matches_filter(s):
                    continue
                t = s.get("last_message_time") or s.get("updated_at")
                ts = t.strftime("%H:%M") if t else ""
                prev = (s.get("last_message") or "")[:48]
                nick = s.get("buyer_nickname") or "买家"
                u = s.get("unread_count", 0) or 0
                unread_suffix = f"  ·  {u}" if u else ""
                label = f"{nick}  |  {ts}{unread_suffix}\n{prev}"
                child = QTreeWidgetItem([label])
                child.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    {"type": "session", "session": s, "account": acc},
                )
                parent.addChild(child)
            parent.setExpanded(True)

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
        self.account_list.reload()
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
        self._render_messages_from_db()
        self._select_tree_session_for_buyer(aid, str(payload["buyer_uid"]))
        try:
            self._hub.total_unread_changed.emit(db_manager.get_total_unread_chat())
        except Exception as e:
            self.logger.debug("total_unread_changed emit: {}", e)

    def _select_tree_session_for_buyer(self, account_id: int, buyer_uid: str) -> None:
        self._refresh_session_trees()
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

    def _on_human_assist_requested(self, payload: dict) -> None:
        """人工协助请求 - 显示弹窗并跳转到实时聊天"""
        try:
            # 提取信息
            account_id = int(payload.get("account_id", 0))
            buyer_uid = str(payload.get("buyer_uid", ""))
            buyer_nickname = str(payload.get("buyer_nickname", "买家"))
            account_name = str(payload.get("login_username", ""))
            question = str(payload.get("question", ""))
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
            
            self.logger.info(f"弹窗已创建，准备显示。父窗口：{self}")
            self._current_assist_dialog.show()
            self.logger.info(f"弹窗已调用 show()，visible={self._current_assist_dialog.isVisible()}")
            
            # 同时显示 InfoBar 通知（作为额外提醒）
            InfoBar.warning(
                title="🔔 买家申请转人工",
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
            
            self.logger.info(f"🚨 开始强制跳转到会话：{buyer_nickname}, account_id={account_id}")
            
            # 获取主窗口
            parent_window = self.window()
            if parent_window and hasattr(parent_window, 'stackedWidget'):
                try:
                    # 通过 stackedWidget 直接切换到实时聊天页面
                    stacked_widget = parent_window.stackedWidget
                    if stacked_widget:
                        for i in range(stacked_widget.count()):
                            widget = stacked_widget.widget(i)
                            if widget is self:
                                # 找到当前聊天 widget，切换到它
                                stacked_widget.setCurrentIndex(i)
                                self.logger.info(f"✅ 已切换到实时聊天页面（索引 {i}）")
                                
                                # 激活窗口，确保在前台
                                parent_window.activateWindow()
                                parent_window.raise_()
                                parent_window.setFocus()
                                
                                # 等待页面切换和 UI 更新完成
                                QTimer.singleShot(500, lambda: self._find_and_select_session_with_focus(account_id, buyer_uid, buyer_nickname))
                                return
                            
                    # 如果找不到，直接尝试选中会话
                    self.logger.warning("未找到实时聊天 widget，直接选中会话")
                    QTimer.singleShot(200, lambda: self._find_and_select_session(account_id, buyer_uid, buyer_nickname))
                        
                except Exception as e:
                    self.logger.error(f"切换页面失败：{e}", exc_info=True)
                    # 失败时直接尝试选中会话
                    QTimer.singleShot(200, lambda: self._find_and_select_session(account_id, buyer_uid, buyer_nickname))
            else:
                self.logger.error("无法获取主窗口或 stackedWidget")
                # 直接尝试选中会话
                QTimer.singleShot(200, lambda: self._find_and_select_session(account_id, buyer_uid, buyer_nickname))
            
        except Exception as e:
            self.logger.error(f"跳转对话窗口失败：{e}", exc_info=True)
    
    def _find_and_select_session_with_focus(self, account_id: int, buyer_uid: str, buyer_nickname: str) -> None:
        """查找并选中会话，同时确保窗口获得焦点"""
        try:
            # 确保窗口在前台
            parent_window = self.window()
            if parent_window:
                parent_window.activateWindow()
                parent_window.raise_()
                parent_window.setFocus()
            
            # 查找并选中会话
            self._find_and_select_session(account_id, buyer_uid, buyer_nickname)
            
        except Exception as e:
            self.logger.error(f"_find_and_select_session_with_focus 失败：{e}", exc_info=True)
    
    def _find_and_select_session(self, account_id: int, buyer_uid: str, buyer_nickname: str) -> None:
        """查找并选中指定会话"""
        try:
            # 刷新会话树
            self._refresh_session_trees()
            
            # 找到并选中该会话
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
                        # 触发点击事件，打开会话
                        self._on_session_clicked(child, 0)
                        self.logger.info(f"✅ 已跳转到会话：{buyer_nickname}")
                        return
            
            self.logger.warning(f"未找到对应的会话：account_id={account_id}, buyer_uid={buyer_uid}")
            
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
            self.browser.clear()
            self._set_chat_enabled(False)
            self._update_header_visuals()
        self._refresh_session_trees()
        self.account_list.reload()
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
        db_manager.set_session_ai_mode(sid, True)
        self._current["ai_mode"] = True
        self._update_header_visuals()
        self.logger.info("会话已自动切回 AI 接待模式（离开聊天窗口）")
        self._show_ai_mode_notice("检测到您已离开聊天窗口，已自动切换为 AI 接待")
    
    def _on_input_activity_timeout(self) -> None:
        """输入框 10 秒无活动，自动切回 AI 模式"""
        if not self._current:
            return
        if self._current.get("ai_mode", True):
            return  # 本来就是 AI 模式，不需要切换
        sid = int(self._current["session_id"])
        db_manager.set_session_ai_mode(sid, True)
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
        if not isinstance(data, dict) or data.get("type") != "session":
            return
        s = data["session"]
        fresh = db_manager.get_chat_session_by_id(int(s["id"]))
        if fresh:
            s = fresh
        acc = data["account"]
        # 切换到其它买家前，若当前会话在人工模式则自动切回 AI
        if self._current and int(self._current.get("session_id", 0)) != int(s["id"]):
            self._restore_ai_for_current_if_manual()
        self._current = {
            "session_id": s["id"],
            "buyer_uid": s["buyer_uid"],
            "buyer_nickname": s.get("buyer_nickname") or "买家",
            "account": acc,
            "ai_mode": s.get("ai_mode", True),
        }
        set_active_chat_session(int(acc["id"]), str(s["buyer_uid"]))
        db_manager.mark_chat_messages_read(int(s["id"]))
        self._update_header_visuals()
        self._set_chat_enabled(True)
        self._rebuild_quick_replies(int(acc["id"]))
        self._render_messages_from_db()
        self.account_list.reload()
        self._refresh_session_trees()
        try:
            self._hub.total_unread_changed.emit(db_manager.get_total_unread_chat())
        except Exception as e:
            self.logger.debug("total_unread_changed emit (session click): {}", e)

    def _render_messages_from_db(self) -> None:
        if not self._current:
            return
        sid = int(self._current["session_id"])
        rows = db_manager.get_chat_messages(sid, limit=_CHAT_HISTORY_LIMIT)
        nick = self._current.get("buyer_nickname") or "买家"
        buyer_letter = _avatar_letter(nick)
        self.browser.clear()
        self.browser.document().setDefaultStyleSheet(
            f"body {{ margin: 0; background: {_C_BG}; color: {_C_MSG_BODY}; }}"
        )
        for m in rows:
            self._append_message_row(
                m["sender_type"],
                m.get("content") or "",
                m.get("sent_at") or m.get("created_at"),
                buyer_letter,
                m.get("content_type"),
                m.get("image_url"),
            )

    def _append_message_row(
        self,
        sender_type: str,
        content: str,
        t: Any,
        buyer_letter: str,
        content_type: Optional[str] = None,
        image_url: Optional[str] = None,
    ):
        if t is None:
            ts = ""
        elif isinstance(t, datetime):
            ts = t.strftime("%H:%M")
        else:
            ts = str(t)[:8]
        ct = (content_type or "text").strip().lower()
        url = (image_url or "").strip()
        if ct == "image" and url:
            body_html = format_chat_bubble_html(url) or html.escape(content or "[图片]")
        elif ct == "video" and url:
            cap = html.escape((content or "[视频]").strip())
            link_part = format_chat_bubble_html(url) or html.escape(url)
            body_html = f'<div style="margin-bottom:6px;">{cap}</div>{link_part}'
        else:
            body_html = html.escape(content or "")
        if sender_type == "customer":
            block = (
                f"<table width='100%' cellpadding='0' cellspacing='0' style='margin:10px 0;'><tr>"
                f"<td align='left'>"
                f"<table cellpadding='0' cellspacing='0' style='max-width:70%;'><tr>"
                f"<td valign='top' style='padding-right:10px;'>"
                f"<span style='display:inline-block;width:36px;height:36px;line-height:36px;"
                f"text-align:center;border-radius:18px;font-weight:bold;font-size:14px;color:#fff;"
                f"background-color:#FF6B6B;'>"
                f"{html.escape(buyer_letter)}</span></td>"
                f"<td valign='top'>"
                f"<div style='background:{_C_CARD};color:{_C_TEXT};padding:10px 14px;border-radius:12px;"
                f"border-bottom-left-radius:4px;font-size:14px;line-height:1.5;'>{body_html}</div>"
                f"<div style='font-size:11px;color:{_C_DIM};margin-top:4px;'>{ts}</div>"
                f"</td></tr></table></td></tr></table>"
            )
        elif sender_type == "ai":
            block = (
                f"<table width='100%' cellpadding='0' cellspacing='0' style='margin:10px 0;'><tr>"
                f"<td align='left'>"
                f"<table cellpadding='0' cellspacing='0' style='max-width:70%;'><tr>"
                f"<td valign='top' style='padding-right:10px;'>"
                f"<span style='display:inline-block;width:36px;height:36px;line-height:36px;"
                f"text-align:center;border-radius:18px;font-weight:bold;font-size:12px;color:#fff;"
                f"background-color:#4C87EB;'>"
                f"AI</span></td>"
                f"<td valign='top'>"
                f"<div style='background:{_C_AI_BUBBLE};color:{_C_TEXT};padding:10px 14px;border-radius:12px;"
                f"border-bottom-left-radius:4px;font-size:14px;line-height:1.5;'>{body_html}</div>"
                f"<div style='font-size:11px;color:{_C_DIM};margin-top:4px;'>{ts}</div>"
                f"</td></tr></table></td></tr></table>"
            )
        elif sender_type == "system":
            block = (
                f"<div style='text-align:center;margin:10px 0;'>"
                f"<span style='display:inline-block;background:{_C_BORDER};color:{_C_MUTED};"
                f"font-size:12px;padding:6px 14px;border-radius:8px;max-width:88%;'>{body_html}</span>"
                f"<div style='font-size:11px;color:{_C_DIM};margin-top:4px;'>{ts}</div></div>"
            )
        else:
            block = (
                f"<table width='100%' cellpadding='0' cellspacing='0' style='margin:10px 0;'><tr>"
                f"<td align='right'>"
                f"<table cellpadding='0' cellspacing='0' align='right' style='max-width:70%;'><tr>"
                f"<td valign='top' style='padding-right:10px;'>"
                f"<div style='background:{_C_ACCENT};color:{_C_TEXT};padding:10px 14px;border-radius:12px;"
                f"border-bottom-right-radius:4px;font-size:14px;line-height:1.5;text-align:left;'>{body_html}</div>"
                f"<div style='font-size:11px;color:{_C_DIM};margin-top:4px;text-align:right;'>{ts}  客服</div>"
                f"</td>"
                f"<td valign='top'>"
                f"<span style='display:inline-block;width:36px;height:36px;line-height:36px;"
                f"text-align:center;border-radius:18px;font-weight:bold;font-size:14px;color:#fff;"
                f"background-color:#22C55E;'>"
                f"我</span></td>"
                f"</tr></table></td></tr></table>"
            )
        self.browser.append(block)
        self.browser.verticalScrollBar().setValue(self.browser.verticalScrollBar().maximum())

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
        db_manager.set_session_ai_mode(sid, ai)
        self._current["ai_mode"] = ai
        self._update_header_visuals()
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
        self.browser.clear()
        self._set_chat_enabled(False)
        self._update_header_visuals()
        self._refresh_session_trees()
        self.account_list.reload()

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
        self.input_edit.clear()
        self._render_messages_from_db()
