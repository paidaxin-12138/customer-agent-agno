"""代申请订单级状态与发卡前检查。"""

import os
import tempfile
import time

import pytest

import database.db_manager as dm_module
import utils.merchant_refund_apply_record as rec_mod
from database.db_manager import DatabaseManager
from utils.merchant_refund_apply_record import (
    RefundApplyGate,
    STATUS_EXPIRED,
    STATUS_FAILED,
    STATUS_PENDING,
    check_refund_apply_gate,
)


@pytest.fixture
def refund_db(tmp_path, monkeypatch):
    """独立 SQLite，避免 DatabaseManager 单例指向生产库。"""
    DatabaseManager._instance = None
    path = str(tmp_path / "refund_apply_test.db")
    db = DatabaseManager(db_path=path)
    dm_module._db_instance = db
    monkeypatch.setattr(rec_mod, "db_manager", db)
    yield db
    dm_module._db_instance = None
    DatabaseManager._instance = None


def test_gate_pending_with_valid_time(refund_db):
    shop, buyer, order = "s1", "b1", "260527-111"
    refund_db.record_merchant_refund_apply(
        shop,
        buyer,
        order,
        api_success=True,
        status=STATUS_PENDING,
        valid_time_unix=int(time.time()) + 3600,
    )
    assert check_refund_apply_gate(shop, order) == RefundApplyGate.PENDING_NOTICE


def test_gate_expired_status(refund_db):
    shop, buyer, order = "s1", "b1", "260527-222"
    refund_db.record_merchant_refund_apply(
        shop, buyer, order, api_success=False, status=STATUS_FAILED
    )
    assert check_refund_apply_gate(shop, order) == RefundApplyGate.EXPIRED_NOTICE
    refund_db.record_merchant_refund_apply(
        shop, buyer, order, api_success=True, status=STATUS_EXPIRED
    )
    assert check_refund_apply_gate(shop, order) == RefundApplyGate.EXPIRED_NOTICE


def test_gate_send_when_no_record(refund_db):
    assert check_refund_apply_gate("s1", "new-order") == RefundApplyGate.SEND


def test_update_from_card_push(refund_db):
    shop, buyer, order = "s1", "b1", "260527-333"
    refund_db.record_merchant_refund_apply(
        shop, buyer, order, api_success=True, status=STATUS_PENDING
    )
    refund_db.update_refund_apply_from_card_push(
        shop,
        buyer,
        order,
        card_msg_id="msg-1",
        valid_time_unix=int(time.time()) + 7200,
        card_expired=False,
    )
    row = refund_db.get_latest_refund_apply_for_order(shop, order)
    assert row is not None
    assert row["card_msg_id"] == "msg-1"
    assert row["status"] == STATUS_PENDING
    assert row["valid_time_unix"] is not None
