# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""处理器链健康检查。"""

from Message.handler_chain_factory import audit_handler_chain, get_handler_chain_status


def test_audit_handler_chain_all_present():
    audit_handler_chain()
    status = get_handler_chain_status()
    assert status["audited"] is True
    assert status["ok"] is True, status.get("errors")
    assert status["missing"] == []
