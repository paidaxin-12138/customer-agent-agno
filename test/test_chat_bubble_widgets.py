"""聊天气泡 Widget 单元测试（无 GUI 窗口）。"""
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QFrame

from ui.widgets.chat_bubble_widgets import (
    CHAT_BG,
    OTHER_BUBBLE,
    OTHER_TEXT,
    SELF_BUBBLE,
    ChatMessageBubbleWidget,
    _BubbleFrame,
    _build_body,
    make_chat_message_item,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_chat_bg_colors():
    assert CHAT_BG == "#1C1C1E"
    assert SELF_BUBBLE == "#0A84FF"
    assert OTHER_BUBBLE == "#2C2C3A"


def test_build_body_plain_text():
    fmt, text = _build_body("改地址", text_color=OTHER_TEXT)
    assert fmt == Qt.TextFormat.PlainText
    assert text == "改地址"


def test_outgoing_bubble_widget(qapp):
    w = ChatMessageBubbleWidget(
        sender_type="human",
        content="测试消息",
        timestamp="12:30",
        is_read=True,
    )
    frame = w.findChild(QFrame, "ChatRightBubbleFrame")
    assert frame is not None
    label = frame.findChild(QLabel)
    assert label is not None
    assert "测试消息" in label.text()


def test_incoming_bubble_widget(qapp):
    w = ChatMessageBubbleWidget(
        sender_type="customer",
        content="买家你好",
        timestamp="12:31",
        buyer_letter="张",
    )
    frame = w.findChild(QFrame, "ChatLeftBubbleFrame")
    assert frame is not None
    label = frame.findChild(QLabel)
    assert label is not None
    assert "买家你好" in label.text()


def test_bubble_frame_plain_text_color(qapp):
    frame = _BubbleFrame(
        side="left",
        text_format=Qt.TextFormat.PlainText,
        text="改地址",
        text_color=OTHER_TEXT,
    )
    label = frame.findChild(QLabel)
    assert OTHER_TEXT in label.styleSheet()


def test_make_chat_message_item(qapp):
    item, widget = make_chat_message_item(
        sender_type="ai",
        content="AI 回复",
        timestamp="12:32",
    )
    assert item is not None
    assert widget is not None
    assert item.sizeHint().height() >= 48
