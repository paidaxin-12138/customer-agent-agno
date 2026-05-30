"""
人工协助弹窗 - 当检测到转人工关键词时显示
显示买家信息、账号信息和最近消息，支持一键跳转对话
"""
from typing import Dict, Any, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
    QFrame,
    QTextEdit,
    QSizePolicy,
    QGraphicsDropShadowEffect,
    QMessageBox,
    QApplication,
)

from config import config
from utils.logger_loguru import get_logger

logger = get_logger("HumanAssistDialog")

_MESSAGE_BOX_MAX_H = 160
_ADDRESS_CHANGE_MESSAGE_MAX_H = 200


class HumanAssistDialog(QDialog):
    """人工协助弹窗"""

    # 点击去处理时发出的信号，携带跳转所需数据
    go_to_chat_requested = pyqtSignal(dict)
    confirm_address_change_requested = pyqtSignal(dict)

    def __init__(self, payload: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.payload = payload
        reason = str(payload.get("reason") or "")
        self._is_address_change = reason == "order_address_change"
        self._shipped_override = False
        if reason == "ai_after_sales_pm":
            self._dialog_title = "🔔 售后问题需人工处理"
        elif reason == "after_sales_policy":
            self._dialog_title = "🔔 售后需人工处理"
        elif self._is_address_change:
            self._dialog_title = "🔔 买家申请改地址"
        else:
            self._dialog_title = "🔔 买家申请转人工"
        self.setWindowTitle(self._dialog_title)
        self.setModal(False)  # 非模态，不阻塞主窗口
        if self._is_address_change:
            self.setMinimumSize(480, 420)
            self.resize(480, 500)
        else:
            self.setMinimumSize(450, 280)
            self.resize(450, 340)
        
        logger.info(f"人工协助弹窗初始化：buyer={payload.get('buyer_nickname', '未知')}")

        # 窗口标志：保持在最前
        # 使用 Dialog 标志，确保在 macOS 上正常显示
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        # 不使用 WA_ShowWithoutActivating，确保窗口获得焦点

        # 初始化 UI
        self._init_ui()
        
        logger.info("人工协助弹窗 UI 初始化完成")

        # 不再自动关闭，等待用户手动操作
        # 如果用户 30 秒内没有操作，才自动关闭
        self._auto_close_timer = QTimer(self)
        self._auto_close_timer.timeout.connect(self.close)
        self._auto_close_timer.setSingleShot(True)
        self._auto_close_timer.start(30000)  # 30 秒后自动关闭
        logger.info("弹窗将在 30 秒后自动关闭")

    def _init_ui(self):
        """初始化界面"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 创建主容器（带圆角和阴影）
        container = QWidget(self)
        container.setObjectName("humanAssistContainer")
        container.setStyleSheet("""
            QWidget#humanAssistContainer {
                background-color: #1E1E1E;
                border-radius: 12px;
                border: 1px solid #3A3A3A;
            }
        """)

        # 添加阴影效果
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setXOffset(0)
        shadow.setYOffset(4)
        shadow.setColor(QColor(0, 0, 0, 100))
        container.setGraphicsEffect(shadow)

        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(24, 20, 24, 20)
        container_layout.setSpacing(16)

        # 标题栏
        title_label = QLabel(getattr(self, "_dialog_title", "🔔 买家申请转人工"))
        title_label.setStyleSheet("""
            QLabel {
                color: #FFFFFF;
                font-size: 16px;
                font-weight: 700;
                font-family: "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif;
            }
        """)
        container_layout.addWidget(title_label)

        # 信息区域（占据中间弹性空间）
        info_widget = self._create_info_widget()
        container_layout.addWidget(info_widget, 1)

        if self._is_address_change:
            shipped_hint = self._create_shipped_hint_widget()
            if shipped_hint is not None:
                container_layout.addWidget(shipped_hint)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        if self._is_address_change:
            self._build_address_change_buttons(button_layout)
        else:
            self._build_default_buttons(button_layout)
        container_layout.addLayout(button_layout)

        layout.addWidget(container)
        QTimer.singleShot(0, self._fit_dialog_to_content)

    def _build_default_buttons(self, button_layout: QHBoxLayout) -> None:
        ignore_btn = QPushButton("稍后再说")
        ignore_btn.setObjectName("ignoreButton")
        ignore_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ignore_btn.setStyleSheet(self._ignore_button_style())
        ignore_btn.clicked.connect(self.close)

        handle_btn = QPushButton("去处理")
        handle_btn.setObjectName("handleButton")
        handle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        handle_btn.setStyleSheet(self._primary_button_style())
        handle_btn.clicked.connect(self._on_handle_clicked)

        button_layout.addStretch()
        button_layout.addWidget(ignore_btn)
        button_layout.addWidget(handle_btn)

    def _build_address_change_buttons(self, button_layout: QHBoxLayout) -> None:
        ignore_btn = QPushButton("稍后再说")
        ignore_btn.setObjectName("ignoreButton")
        ignore_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ignore_btn.setStyleSheet(self._ignore_button_style())
        ignore_btn.clicked.connect(self.close)

        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("cancelButton")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(self._ignore_button_style())
        cancel_btn.clicked.connect(self._on_address_change_cancel)

        self._confirm_btn = QPushButton("确认改址")
        self._confirm_btn.setObjectName("confirmAddressButton")
        self._confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        eligible = str(self.payload.get("address_change_eligible") or "ok")
        if eligible == "shipped" and not self._shipped_override:
            self._confirm_btn.setEnabled(False)
            self._confirm_btn.setStyleSheet(self._disabled_button_style())
        else:
            self._confirm_btn.setStyleSheet(self._primary_button_style())
        self._confirm_btn.clicked.connect(self._on_confirm_address_change)

        button_layout.addStretch()
        button_layout.addWidget(ignore_btn)
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(self._confirm_btn)

    @staticmethod
    def _ignore_button_style() -> str:
        return """
            QPushButton#ignoreButton, QPushButton#cancelButton {
                background-color: transparent;
                color: #8E8E93;
                border: 1px solid #3A3A3A;
                border-radius: 8px;
                padding: 10px 20px;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton#ignoreButton:hover, QPushButton#cancelButton:hover {
                background-color: #2C2C2E;
                color: #FFFFFF;
            }
            QPushButton#ignoreButton:pressed, QPushButton#cancelButton:pressed {
                background-color: #3A3A3A;
            }
        """

    @staticmethod
    def _primary_button_style() -> str:
        return """
            QPushButton#handleButton, QPushButton#confirmAddressButton {
                background-color: #0A84FF;
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                padding: 10px 24px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton#handleButton:hover, QPushButton#confirmAddressButton:hover {
                background-color: #0070E0;
            }
            QPushButton#handleButton:pressed, QPushButton#confirmAddressButton:pressed {
                background-color: #0058B8;
            }
        """

    @staticmethod
    def _disabled_button_style() -> str:
        return """
            QPushButton#confirmAddressButton {
                background-color: #48484A;
                color: #8E8E93;
                border: none;
                border-radius: 8px;
                padding: 10px 24px;
                font-size: 13px;
                font-weight: 600;
            }
        """

    def _create_shipped_hint_widget(self) -> Optional[QWidget]:
        eligible = str(self.payload.get("address_change_eligible") or "ok")
        if eligible != "shipped":
            return None

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        hint = str(
            config.get(
                "chat.address_change_shipped_confirm_hint",
                "该订单已发货，平台可能不允许改址。操作后无法撤销，是否仍尝试修改？",
            )
        )
        hint_label = QLabel(f"⚠️ {hint}")
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet("""
            QLabel {
                color: #FFD60A;
                background-color: #3A3200;
                border-radius: 8px;
                padding: 10px 12px;
                font-size: 12px;
            }
        """)
        layout.addWidget(hint_label)

        override_btn = QPushButton("仍要尝试修改")
        override_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        override_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #FFD60A;
                border: 1px solid #FFD60A;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #3A3200; }
        """)
        override_btn.clicked.connect(self._on_shipped_override)
        layout.addWidget(override_btn)
        return widget

    def _on_shipped_override(self) -> None:
        self._shipped_override = True
        if hasattr(self, "_confirm_btn"):
            self._confirm_btn.setEnabled(True)
            self._confirm_btn.setStyleSheet(self._primary_button_style())

    def _on_address_change_cancel(self) -> None:
        self._auto_close_timer.stop()
        out = dict(self.payload)
        out["focus_topic"] = "address_change"
        self.go_to_chat_requested.emit(out)
        self.close()

    def _on_confirm_address_change(self) -> None:
        eligible = str(self.payload.get("address_change_eligible") or "ok")
        if eligible == "shipped":
            hint = str(
                config.get(
                    "chat.address_change_shipped_confirm_hint",
                    "该订单已发货，平台可能不允许改址。操作后无法撤销，是否仍尝试修改？",
                )
            )
            reply = QMessageBox.question(
                self,
                "确认改址",
                hint,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._auto_close_timer.stop()
        out = dict(self.payload)
        out["shipped_override"] = bool(
            self._shipped_override or eligible == "shipped"
        )
        self.confirm_address_change_requested.emit(out)
        self.close()

    def _create_info_widget(self) -> QWidget:
        """创建信息展示区域"""
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # 买家信息
        buyer_layout = QHBoxLayout()
        buyer_layout.setSpacing(8)

        # 买家头像（字母）
        avatar_label = QLabel(self._get_avatar_letter())
        avatar_label.setFixedSize(40, 40)
        avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar_label.setStyleSheet("""
            QLabel {
                background-color: #0A84FF;
                color: #FFFFFF;
                border-radius: 20px;
                font-size: 18px;
                font-weight: 600;
                font-family: "SF Pro Text";
            }
        """)
        buyer_layout.addWidget(avatar_label)

        # 买家名称
        buyer_name = self.payload.get("buyer_nickname", "买家")
        buyer_name_label = QLabel(buyer_name)
        buyer_name_label.setStyleSheet("""
            QLabel {
                color: #FFFFFF;
                font-size: 14px;
                font-weight: 600;
                font-family: "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif;
            }
        """)
        buyer_layout.addWidget(buyer_name_label)

        buyer_layout.addStretch()
        layout.addLayout(buyer_layout)

        # 账号信息
        login_username = self.payload.get("login_username", "")
        if not login_username:
            login_username = self.payload.get("account_name", "未知账号")
        
        account_info = self._create_info_row(
            "🏪 账号名称",
            login_username,
        )
        layout.addWidget(account_info)

        # 店铺信息（如果有）
        shop_name = self.payload.get("shop_name", "")
        if shop_name:
            shop_info = self._create_info_row("📦 店铺", shop_name)
            layout.addWidget(shop_info)

        if self._is_address_change:
            order_sn = str(self.payload.get("order_sn") or "")
            goods_name = str(self.payload.get("goods_name") or "")
            status_str = str(self.payload.get("order_status_str") or "")
            if order_sn:
                layout.addWidget(self._create_info_row("📋 订单号", order_sn))
            if goods_name:
                layout.addWidget(self._create_info_row("🛍 商品", goods_name))
            if status_str:
                layout.addWidget(self._create_info_row("📦 状态", status_str))

            pa = self.payload.get("parsed_address") or {}
            addr_parts = [
                pa.get("province", ""),
                pa.get("city", ""),
                pa.get("district", ""),
                pa.get("detail", ""),
            ]
            addr_body = "".join(str(p) for p in addr_parts if p)
            name = str(pa.get("name") or "")
            mobile = str(pa.get("mobile") or "")
            addr_line = f"{addr_body} {name} {mobile}".strip()
            if addr_line:
                layout.addWidget(self._create_info_row("📍 新地址", addr_line))

        # 最近消息 / 摘要
        reason = str(self.payload.get("reason") or "")
        if reason in ("ai_after_sales_pm", "after_sales_policy"):
            message_label = QLabel("📋 问题摘要")
        elif self._is_address_change:
            message_label = QLabel("💬 买家原话")
        else:
            message_label = QLabel("💬 最近消息")
        message_label.setStyleSheet("""
            QLabel {
                color: #8E8E93;
                font-size: 12px;
                font-weight: 600;
                font-family: "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif;
            }
        """)
        layout.addWidget(message_label)

        # 消息内容
        question = (
            self.payload.get("summary")
            or self.payload.get("question")
            or ""
        )

        message_content = self._create_message_box(question or "无消息内容")
        self._message_box_frame = message_content
        layout.addWidget(message_content, 1)
        self._refresh_message_box_height()

        return widget

    def _create_message_box(self, text: str) -> QFrame:
        """最近消息容器：固定最大高度，内容过长时内部滚动。"""
        frame = QFrame()
        frame.setObjectName("recentMessageBox")
        max_h = (
            _ADDRESS_CHANGE_MESSAGE_MAX_H
            if self._is_address_change
            else _MESSAGE_BOX_MAX_H
        )
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        frame.setMaximumHeight(max_h + 20)
        frame.setStyleSheet("""
            QFrame#recentMessageBox {
                background-color: #2C2C2E;
                border-radius: 8px;
                border: none;
            }
        """)
        box_layout = QVBoxLayout(frame)
        box_layout.setContentsMargins(12, 10, 12, 10)
        box_layout.setSpacing(0)

        editor = QTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(text)
        editor.setFrameShape(QFrame.Shape.NoFrame)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        editor.setFixedHeight(max_h)
        editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        editor.setStyleSheet("""
            QTextEdit {
                color: #E5E5EA;
                background: transparent;
                font-size: 13px;
                line-height: 150%;
                border: none;
                padding: 0;
            }
        """)
        box_layout.addWidget(editor)
        self._message_box_editor = editor
        self._message_box_max_h = max_h
        return frame

    def _refresh_message_box_height(self) -> None:
        """按实际宽度重排消息文本换行（高度固定，内部滚动）。"""
        editor = getattr(self, "_message_box_editor", None)
        frame = getattr(self, "_message_box_frame", None)
        if editor is None or frame is None:
            return
        max_h = getattr(self, "_message_box_max_h", _MESSAGE_BOX_MAX_H)
        frame_w = frame.width()
        if frame_w <= 0:
            frame_w = max(self.width() - 48, 360)
        doc = editor.document()
        doc.setTextWidth(max(frame_w - 24, 200))
        editor.setFixedHeight(max_h)

    def _fit_dialog_to_content(self) -> None:
        """根据内容微调弹窗高度，避免超出屏幕可用区域。"""
        self._refresh_message_box_height()
        self.adjustSize()
        hint = self.sizeHint()
        min_h = 420 if self._is_address_change else 280
        max_h = 560 if self._is_address_change else 480
        w = max(self.minimumWidth(), hint.width())
        h = max(min_h, min(hint.height() + 12, max_h))
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            w = min(w, avail.width() - 32)
            h = min(h, avail.height() - 32)
        self.resize(w, h)

    def _create_info_row(self, label_text: str, value_text: str) -> QWidget:
        """创建单行信息"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        label = QLabel(label_text)
        label.setStyleSheet("""
            QLabel {
                color: #8E8E93;
                font-size: 11px;
                font-family: "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif;
            }
        """)
        label.setFixedWidth(100)
        layout.addWidget(label)

        value = QLabel(value_text)
        value.setStyleSheet("""
            QLabel {
                color: #E5E5EA;
                font-size: 12px;
                font-weight: 500;
                font-family: "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif;
            }
        """)
        value.setWordWrap(True)
        value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(value, 1)
        return widget

    def _get_avatar_letter(self) -> str:
        """获取买家头像字母"""
        buyer_name = self.payload.get("buyer_nickname", "买家")
        if not buyer_name or buyer_name == "买家":
            return "买"
        return buyer_name[0].upper() if buyer_name.isascii() else buyer_name[0]

    def _on_handle_clicked(self):
        """点击去处理按钮"""
        # 停止自动关闭定时器
        self._auto_close_timer.stop()

        # 发出跳转信号
        self.go_to_chat_requested.emit(self.payload)

        # 关闭弹窗
        self.close()

    def showEvent(self, event):
        """窗口显示时的处理"""
        super().showEvent(event)
        
        # 先激活窗口，确保它会被显示
        self.activateWindow()
        self.raise_()
        
        logger.info(f"人工协助弹窗已显示，位置：{self.x()}, {self.y()}")
        
        # 窗口居中显示
        self._center_on_parent()
        self._refresh_message_box_height()
        self._fit_dialog_to_content()
        
        # 再次激活，确保在最前面
        QTimer.singleShot(100, self._bring_to_front)

    def _bring_to_front(self):
        """将窗口带到最前面"""
        if self.isVisible():
            self.activateWindow()
            self.raise_()
            logger.info("弹窗已带到最前面")

    def _center_on_parent(self):
        """在父窗口或屏幕居中显示，并确保不超出可用区域。"""
        my_rect = self.geometry()
        if self.parent() and self.parent().isVisible():
            parent_rect = self.parent().geometry()
            x = parent_rect.x() + (parent_rect.width() - my_rect.width()) // 2
            y = parent_rect.y() + (parent_rect.height() - my_rect.height()) // 2
        else:
            screen = self.window().screen() or QApplication.primaryScreen()
            if not screen:
                return
            screen_geometry = screen.availableGeometry()
            x = screen_geometry.x() + (screen_geometry.width() - my_rect.width()) // 2
            y = screen_geometry.y() + (screen_geometry.height() - my_rect.height()) // 2

        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            x = max(avail.x(), min(x, avail.right() - my_rect.width() + 1))
            y = max(avail.y(), min(y, avail.bottom() - my_rect.height() + 1))

        self.move(x, y)
        logger.info(f"弹窗已居中：{x}, {y}")
