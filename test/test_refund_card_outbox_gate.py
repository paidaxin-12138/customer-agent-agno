"""退货卡 outbox 门禁：防同单重复发卡导致一点就过期。"""
import sqlite3
import time
from unittest.mock import MagicMock, patch

import pytest

import database.db_manager as dm_module
import utils.merchant_refund_apply_record as rec_mod
from database.db_manager import DatabaseManager
from utils.merchant_refund_apply_record import (
    REFUND_GATE_BLOCKED_PREFIX,
    REFUND_GATE_SKIP_PREFIX,
    RefundCardSendAction,
    STATUS_PENDING,
    evaluate_refund_card_send_gate,
    note_refund_card_mms_success,
)
from utils.outbound_mms_dispatch import execute_outbox_mms_send
from utils.outbound_outbox_retry import retry_outbox_row_sync


def _refund_row(**overrides):
    base = {
        "id": 9,
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
        "channel_name": "pinduoduo",
        "sender_type": "ai",
        "login_username": "",
    }
    base.update(overrides)
    return base


def test_evaluate_gate_skip_when_pending_in_db(refund_db):
    refund_db.record_merchant_refund_apply(
        "s1",
        "b1",
        "O1",
        api_success=True,
        status=STATUS_PENDING,
        valid_time_unix=int(time.time()) + 3600,
    )
    assert (
        evaluate_refund_card_send_gate("s1", "b1", "O1")
        == RefundCardSendAction.SKIP_ALREADY_SENT
    )


def test_execute_refund_card_skips_duplicate_without_mms():
    row = _refund_row()
    sender = MagicMock()
    with patch(
        "Channel.pinduoduo.utils.API.send_message.SendMessage",
        return_value=sender,
    ), patch(
        "utils.merchant_refund_apply_record.evaluate_refund_card_send_gate",
        return_value=RefundCardSendAction.SKIP_ALREADY_SENT,
    ):
        ok, err = execute_outbox_mms_send(row)
    assert ok is True
    assert err == REFUND_GATE_SKIP_PREFIX
    sender.send_ask_refund_apply.assert_not_called()


def test_execute_refund_card_unshipped_forces_question_type_zero():
    row = _refund_row()
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
    ) as note_mock:
        ok, err = execute_outbox_mms_send(row)
    assert ok is True
    assert err == ""
    sender.send_ask_refund_apply.assert_called_once_with(
        "O1",
        after_sales_type=1,
        question_type=0,
        refund_amount=100,
        message=None,
        user_ship_status=0,
    )
    note_mock.assert_called_once()


def test_execute_refund_card_gate_blocked():
    row = _refund_row()
    sender = MagicMock()
    with patch(
        "Channel.pinduoduo.utils.API.send_message.SendMessage",
        return_value=sender,
    ), patch(
        "utils.merchant_refund_apply_record.evaluate_refund_card_send_gate",
        return_value=RefundCardSendAction.BLOCK_EXPIRED,
    ):
        ok, err = execute_outbox_mms_send(row)
    assert ok is False
    assert err.startswith(REFUND_GATE_BLOCKED_PREFIX)
    sender.send_ask_refund_apply.assert_not_called()


def test_note_refund_card_mms_success_records_pending(refund_db):
    note_refund_card_mms_success(
        "s1",
        "b1",
        "O1",
        after_sales_type=1,
        refund_amount_fen=100,
    )
    row = refund_db.get_latest_refund_apply_for_order("s1", "O1")
    assert row is not None
    assert row["status"] == STATUS_PENDING
    assert row["api_success"] is True


def test_retry_refund_card_not_skipped_by_text_receipt(outbox_db, monkeypatch):
    """同会话有文本回执时，退货卡仍应尝试 MMS（或门禁），不能误 mark_sent。"""
    from database.outbound_outbox import create_pending, get_row, mark_failed

    oid = create_pending(
        session_id=21,
        account_id=10,
        channel_name="pinduoduo",
        shop_id="s1",
        user_id="u1",
        buyer_uid="b1",
        content="[refund_apply] order=O1",
        message_kind="refund_apply_card",
        payload={
            "order_sn": "O1",
            "after_sales_type": 1,
            "question_type": 0,
            "refund_amount": 100,
            "user_ship_status": 0,
        },
    )
    row = get_row(int(oid))
    assert row is not None
    mark_failed(int(oid), "prev")
    row = get_row(int(oid))

    monkeypatch.setattr(
        "utils.outbound_receipt.has_recent_outbound_receipt",
        lambda *args, **kwargs: True,
    )
    execute_mock = MagicMock(return_value=(True, REFUND_GATE_SKIP_PREFIX))
    with patch(
        "utils.outbound_mms_dispatch.execute_outbox_mms_send",
        execute_mock,
    ):
        ok = retry_outbox_row_sync(row)
    assert ok is True
    execute_mock.assert_called_once()


def test_retry_abandons_when_gate_blocked(outbox_db, monkeypatch):
    from database.outbound_outbox import create_pending, get_row, mark_failed

    oid = create_pending(
        session_id=20,
        account_id=10,
        channel_name="pinduoduo",
        shop_id="s1",
        user_id="u1",
        buyer_uid="b1",
        content="[refund_apply] order=O1",
        message_kind="refund_apply_card",
        payload={
            "order_sn": "O1",
            "after_sales_type": 1,
            "question_type": 0,
            "refund_amount": 100,
            "user_ship_status": 0,
        },
    )
    row = get_row(int(oid))
    assert row is not None
    mark_failed(int(oid), "prev")
    row = get_row(int(oid))
    abandoned = []

    monkeypatch.setattr(
        "database.outbound_outbox.mark_abandoned",
        lambda oid, reason: abandoned.append((oid, reason)),
    )
    monkeypatch.setattr(
        "utils.outbound_receipt.has_recent_outbound_receipt",
        lambda *args, **kwargs: False,
    )
    with patch(
        "utils.outbound_mms_dispatch.execute_outbox_mms_send",
        return_value=(False, f"{REFUND_GATE_BLOCKED_PREFIX}expired_or_failed"),
    ):
        ok = retry_outbox_row_sync(row)
    assert ok is False
    assert abandoned and abandoned[0][0] == int(oid)


@pytest.fixture
def outbox_db(tmp_path, monkeypatch):
    db_file = tmp_path / "outbox_gate.db"
    monkeypatch.setenv("CUSTOMER_AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("database.outbound_outbox.outbox_enabled", lambda: True)
    monkeypatch.setattr(
        "database.outbound_outbox._db_path",
        lambda: str(db_file),
    )
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE outbound_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            account_id INTEGER NOT NULL,
            channel_name TEXT NOT NULL DEFAULT 'pinduoduo',
            shop_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            buyer_uid TEXT NOT NULL,
            login_username TEXT,
            content TEXT NOT NULL,
            message_kind TEXT NOT NULL DEFAULT 'text',
            payload_json TEXT,
            sender_type TEXT NOT NULL DEFAULT 'ai',
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            created_at REAL NOT NULL,
            last_attempt_at REAL,
            sent_at REAL,
            chat_message_id INTEGER,
            error_detail TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    yield db_file


@pytest.fixture
def refund_db(tmp_path, monkeypatch):
    DatabaseManager._instance = None
    path = str(tmp_path / "refund_gate.db")
    db = DatabaseManager(db_path=path)
    dm_module._db_instance = db
    monkeypatch.setattr(rec_mod, "db_manager", db)
    yield db
    dm_module._db_instance = None
    DatabaseManager._instance = None
