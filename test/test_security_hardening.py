"""安全加固：审计脱敏、outbox 错误脱敏。"""
from database.outbound_outbox import _sanitize_error_detail


def test_sanitize_outbox_error_strips_bearer():
    raw = "send failed Bearer sk-live-secret-token-abcdefghij"
    out = _sanitize_error_detail(raw)
    assert "sk-live" not in out
    assert "***" in out


def test_audit_refund_card_masks_identifiers(monkeypatch):
    captured = []

    def fake_insert(row):
        captured.append(row)

    monkeypatch.setattr(
        "database.ops_repository.get_ops_repository",
        lambda: type(
            "R",
            (),
            {"insert_security_audit": staticmethod(fake_insert)},
        )(),
    )
    from utils.audit_log import audit_refund_card

    audit_refund_card(
        "260527-006427778640457",
        shop_id="shop1",
        buyer_uid="4216881609",
        success=True,
    )
    assert captured
    row = captured[0]
    assert "006427778640457" not in row["user_label"]
    assert "4216881609" not in row["payload_json"]
