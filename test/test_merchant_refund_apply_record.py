"""商家代申请退款次数统计。"""

import time

import pytest

import database.db_manager as dm_module
import utils.merchant_refund_apply_record as rec_mod
from database.db_manager import DatabaseManager


@pytest.fixture
def refund_db(tmp_path, monkeypatch):
    DatabaseManager._instance = None
    path = str(tmp_path / "refund_counts.db")
    db = DatabaseManager(db_path=path)
    dm_module._db_instance = db
    monkeypatch.setattr(rec_mod, "db_manager", db)
    yield db
    dm_module._db_instance = None
    DatabaseManager._instance = None


def test_merchant_refund_apply_counts(refund_db):
    shop, buyer, order = "570414651", "4216881609", "260527-281154721360457"
    refund_db.record_merchant_refund_apply(
        shop, buyer, order, api_success=True, after_sales_type=1, refund_amount_fen=200
    )
    refund_db.record_merchant_refund_apply(
        shop, buyer, order, api_success=True, after_sales_type=1, refund_amount_fen=200
    )
    refund_db.record_merchant_refund_apply(
        shop, buyer, "260527-other", api_success=False, error_msg="quota"
    )
    c = refund_db.merchant_refund_apply_counts(shop, buyer, order)
    assert c["order_total"] == 2
    assert c["buyer_today"] >= 2
    assert c["shop_today"] >= 2
    refund_db.update_refund_apply_from_card_push(
        shop,
        buyer,
        order,
        card_msg_id="1779868383550",
        valid_time_unix=None,
        card_expired=True,
    )
    from database.models import MerchantRefundApplyLog

    session = refund_db.get_session()
    try:
        row = (
            session.query(MerchantRefundApplyLog)
            .filter(MerchantRefundApplyLog.order_sn == order)
            .order_by(MerchantRefundApplyLog.id.desc())
            .first()
        )
        assert row is not None
        assert row.card_expired is True
        assert row.card_msg_id == "1779868383550"
        assert row.status == "expired"
    finally:
        session.close()
