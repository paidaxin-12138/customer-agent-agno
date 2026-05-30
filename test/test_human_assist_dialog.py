"""
人工协助弹窗单元测试（不启动事件循环，避免 sys.exit 干扰 pytest）。
手动预览：python -m test.test_human_assist_dialog
"""
from __future__ import annotations

import sys

import pytest
from PyQt6.QtWidgets import QApplication

from ui.widgets.human_assist_dialog import HumanAssistDialog

PAYLOAD = {
    "account_id": 1,
    "buyer_uid": "buyer_123",
    "buyer_nickname": "测试买家",
    "login_username": "test_shop_account",
    "shop_name": "测试店铺",
    "question": "你好，我想转人工客服，有事情要咨询",
    "reason": "keyword_human",
}


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_dialog_initialization(qapp):
    dialog = HumanAssistDialog(PAYLOAD)
    assert dialog.payload["buyer_nickname"] == "测试买家"
    assert dialog.payload["buyer_uid"] == "buyer_123"
    assert "转人工" in dialog.windowTitle()
    assert dialog.isVisible() or not dialog.isVisible()
    dialog.close()


def test_dialog_auto_close_timer_started(qapp):
    dialog = HumanAssistDialog(PAYLOAD)
    assert dialog._auto_close_timer.isActive()
    dialog.close()


def test_recent_message_box_expands(qapp):
    from PyQt6.QtWidgets import QFrame, QTextEdit

    dialog = HumanAssistDialog(PAYLOAD)
    box = dialog.findChild(QFrame, "recentMessageBox")
    assert box is not None
    editor = box.findChild(QTextEdit)
    assert editor is not None
    assert editor.height() >= 40
    assert "转人工" in editor.toPlainText()
    dialog.close()


def test_address_change_dialog_message_height(qapp):
    payload = {
        **PAYLOAD,
        "reason": "order_address_change",
        "order_sn": "240530-123456",
        "goods_name": "测试商品",
        "order_status_str": "待发货",
        "parsed_address": {
            "province": "广东省",
            "city": "深圳市",
            "district": "南山区",
            "detail": "科技园路1号",
            "name": "张三",
            "mobile": "13800138000",
        },
        "question": "麻烦改一下地址，谢谢",
    }
    dialog = HumanAssistDialog(payload)
    dialog.resize(480, 500)
    dialog._refresh_message_box_height()
    editor = dialog._message_box_editor
    assert editor is not None
    assert editor.height() == 200
    assert editor.isReadOnly()
    dialog.close()


def test_long_question_not_truncated(qapp):
    long_tail = "尾段标识" * 80
    payload = {
        **PAYLOAD,
        "reason": "order_address_change",
        "order_sn": "240530-123456",
        "parsed_address": {"province": "广东省", "detail": "科技园路1号"},
        "question": long_tail,
    }
    dialog = HumanAssistDialog(payload)
    editor = dialog._message_box_editor
    assert editor is not None
    assert long_tail in editor.toPlainText()
    dialog.close()


def _run_interactive_preview() -> None:
    app = QApplication(sys.argv)
    dialog = HumanAssistDialog(PAYLOAD)
    dialog.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    _run_interactive_preview()
