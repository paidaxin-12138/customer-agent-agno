"""改址处理器审计日志单元测试。"""
from unittest.mock import patch

from Message.handlers.address_change_handler import _audit_address_change


def test_audit_address_change_success():
    with patch("utils.audit_log.audit_log") as mock_audit:
        _audit_address_change(
            order_sn="250105-123456789012345",
            detail="改址弹窗已推送",
            success=True,
            from_uid="buyer_1",
            shop_id="shop_1",
        )
        mock_audit.assert_called_once()
        args, kwargs = mock_audit.call_args
        assert args[0] == "address_change"
        assert args[1] == "250105-123456789012345"
        assert kwargs["operator"] == "buyer"
        assert kwargs["severity"] == "info"
        assert kwargs["extra"]["success"] is True


def test_audit_address_change_failure():
    with patch("utils.audit_log.audit_log") as mock_audit:
        _audit_address_change(
            order_sn="",
            detail="改址查单失败",
            success=False,
            from_uid="buyer_2",
            shop_id="shop_2",
        )
        mock_audit.assert_called_once()
        args, kwargs = mock_audit.call_args
        assert args[0] == "address_change"
        assert args[1] == "buyer_2"
        assert kwargs["severity"] == "warn"
