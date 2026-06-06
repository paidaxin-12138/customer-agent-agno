"""处理器链健康检查。"""

from Message.handler_chain_factory import audit_handler_chain, get_handler_chain_status


def test_audit_handler_chain_all_present():
    audit_handler_chain()
    status = get_handler_chain_status()
    assert status["audited"] is True
    assert status["ok"] is True, status.get("errors")
    assert status["missing"] == []
