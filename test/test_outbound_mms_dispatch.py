"""Outbox MMS 按 message_kind 分发。"""
from unittest.mock import MagicMock, patch

from utils.merchant_refund_apply_record import RefundCardSendAction
from utils.outbound_mms_dispatch import execute_outbox_mms_send


def test_execute_refund_apply_card():
    row = {
        "message_kind": "refund_apply_card",
        "shop_id": "s1",
        "user_id": "u1",
        "buyer_uid": "b1",
        "content": "[refund_apply] order=O1",
        "payload_json": {
            "order_sn": "O1",
            "after_sales_type": 3,
            "question_type": 1,
            "refund_amount": 100,
            "user_ship_status": 0,
        },
    }
    sender = MagicMock()
    sender.send_ask_refund_apply.return_value = {"success": True}
    with patch(
        "Channel.pinduoduo.utils.API.send_message.SendMessage",
        return_value=sender,
    ), patch(
        "utils.merchant_refund_apply_record.evaluate_refund_card_send_gate",
        return_value=RefundCardSendAction.SEND,
    ), patch(
        "utils.merchant_refund_apply_record.note_refund_card_mms_success",
    ):
        ok, err = execute_outbox_mms_send(row)
    assert ok is True
    assert err == ""
    sender.send_ask_refund_apply.assert_called_once()


def test_execute_image():
    row = {
        "message_kind": "image",
        "shop_id": "s1",
        "user_id": "u1",
        "buyer_uid": "b1",
        "content": "https://img.example.com/a.png",
        "payload_json": {"image_url": "https://img.example.com/a.png"},
    }
    sender = MagicMock()
    sender.send_image.return_value = {"success": True}
    with patch(
        "Channel.pinduoduo.utils.API.send_message.SendMessage",
        return_value=sender,
    ):
        ok, err = execute_outbox_mms_send(row)
    assert ok is True
    sender.send_image.assert_called_once_with(
        "b1", "https://img.example.com/a.png"
    )


def test_execute_goods_card():
    row = {
        "message_kind": "goods_card",
        "shop_id": "s1",
        "user_id": "u1",
        "buyer_uid": "b1",
        "content": "[goods_card] goods_id=99",
        "payload_json": {"goods_id": 99, "biz_type": 2},
    }
    sender = MagicMock()
    sender.send_mallGoodsCard.return_value = {"success": True}
    with patch(
        "Channel.pinduoduo.utils.API.send_message.SendMessage",
        return_value=sender,
    ):
        ok, err = execute_outbox_mms_send(row)
    assert ok is True
    sender.send_mallGoodsCard.assert_called_once_with("b1", 99, biz_type=2)
