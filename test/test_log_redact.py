from utils.log_redact import redact_log_payload, redact_string_value


def test_redact_phone_and_order_sn():
    s = "联系 13812345678 订单 250530-123456789012345"
    out = redact_string_value(s)
    assert "13812345678" not in out
    assert "***" in out


def test_redact_nested_dict_keys():
    payload = {
        "mobile": "13900001111",
        "nested": {"cookie": "a=1; b=2"},
        "msg": "ok",
    }
    out = redact_log_payload(payload)
    assert out["mobile"] == "***"
    assert out["nested"]["cookie"] == "***"
    assert out["msg"] == "ok"
