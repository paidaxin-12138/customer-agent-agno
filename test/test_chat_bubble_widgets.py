"""聊天气泡 Widget 单元测试（无 GUI 窗口）。"""
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QFrame, QWidget

from ui.widgets.chat_bubble_widgets import (
    CHAT_BG,
    OTHER_BUBBLE,
    OTHER_TEXT,
    SELF_BUBBLE,
    ChatMessageBubbleWidget,
    _BubbleFrame,
    _build_body,
    make_chat_message_item,
    make_chat_message_widget,
    reflow_message_widgets,
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
    label = frame.findChild(QLabel, "ChatBubbleBodyLabel")
    assert label is not None
    assert "测试消息" in label.text()
    time_lbl = w.findChild(QLabel, "ChatBubbleTime")
    assert time_lbl is not None
    assert "12:30" in time_lbl.text()
    assert "客服" in time_lbl.text()
    assert "已读" not in time_lbl.text()
    assert "未读" not in time_lbl.text()


def test_incoming_bubble_widget(qapp):
    w = ChatMessageBubbleWidget(
        sender_type="customer",
        content="买家你好",
        timestamp="12:31",
        buyer_letter="张",
    )
    frame = w.findChild(QFrame, "ChatLeftBubbleFrame")
    assert frame is not None
    label = frame.findChild(QLabel, "ChatBubbleBodyLabel")
    assert label is not None
    assert "买家你好" in label.text()


def test_image_bubble_uses_pixmap_loader(qapp):
    w = ChatMessageBubbleWidget(
        sender_type="customer",
        content="",
        timestamp="12:33",
        content_type="image",
        image_url="https://example.com/photo.jpg",
    )
    frame = w.findChild(QFrame, "ChatLeftBubbleFrame")
    assert frame is not None
    body = frame.findChild(QWidget, "ChatBubbleBodyImage")
    assert body is not None
    placeholder = body.findChild(QLabel, "ChatBubbleImagePlaceholder")
    assert placeholder is not None
    assert "加载中" in placeholder.text()


def test_multiline_ai_bubble_frame_height(qapp):
    text = (
        "亲亲，小店给您发了商品卡片，是「功能底胶封层甲油胶套装」，"
        "价格2元。您点开卡片看看详情，满意再拍哈。"
    )
    frame = _BubbleFrame(
        side="left",
        text_format=Qt.TextFormat.PlainText,
        text=text,
        text_color=OTHER_TEXT,
    )
    frame_h = frame.reflow(320)
    label = frame.findChild(QLabel, "ChatBubbleBodyLabel")
    assert label is not None
    vm = frame.layout().contentsMargins().top() + frame.layout().contentsMargins().bottom()
    assert frame_h >= label.height() + vm


def test_bubble_reflow(qapp):
    w = ChatMessageBubbleWidget(
        sender_type="human",
        content="长消息" * 20,
        timestamp="12:34",
    )
    h_narrow = w.reflow(400)
    h_wide = w.reflow(800)
    assert h_narrow >= 48
    assert h_wide >= 48


def test_reflow_message_widgets(qapp):
    from PyQt6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

    scroll = QScrollArea()
    scroll.resize(500, 600)
    container = QWidget()
    container.setObjectName("LiveChatMsgList")
    layout = QVBoxLayout(container)
    widget = make_chat_message_widget(
        sender_type="customer",
        content="测试",
        timestamp="12:35",
        list_width=500,
    )
    layout.addWidget(widget)
    scroll.setWidget(container)
    reflow_message_widgets(container, layout, 500)
    assert widget.height() >= 48


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
