"""
统一安全审计：写入 ops_security_audits（与运营看板共用表结构）。
字段映射：action→event_type, target→user_label, operator/detail→detail+payload_json
"""
from __future__ import annotations

import json
import socket
from typing import Any, Dict, Optional

from utils.logger_loguru import get_logger

_logger = get_logger("AuditLog")


def _local_ip() -> Optional[str]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def audit_log(
    action: str,
    target: str,
    detail: str,
    operator: str = "system",
    *,
    severity: str = "info",
    ip_address: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """
    记录审计事件。表不存在时由 OpsRepository.ensure_tables 自动创建。
    """
    payload: Dict[str, Any] = {
        "operator": operator,
        "target": target,
        "ip_address": ip_address or _local_ip(),
    }
    if extra:
        payload.update(extra)
    row = {
        "event_type": (action or "unknown")[:50],
        "user_label": (target or "")[:200] or None,
        "detail": f"[{operator}] {detail}"[:4000] if detail else f"[{operator}]",
        "severity": severity[:20] if severity else "info",
        "payload_json": json.dumps(payload, ensure_ascii=False),
    }
    try:
        from database.ops_repository import get_ops_repository

        get_ops_repository().insert_security_audit(row)
    except Exception as e:
        _logger.error("audit_log 写入失败 action={} target={}: {}", action, target, e)


def audit_login(username: str, success: bool, *, shop_id: str = "", detail: str = "") -> None:
    audit_log(
        "account_login" if success else "account_login_failed",
        username or shop_id or "unknown",
        detail or ("登录成功" if success else "登录失败"),
        operator=username or "system",
        severity="info" if success else "warn",
        extra={"shop_id": shop_id, "success": success},
    )


def audit_logout(username: str, *, detail: str = "登出") -> None:
    audit_log("account_logout", username, detail, operator=username)


def audit_keyword_change(action: str, keyword: str, *, operator: str = "ui") -> None:
    audit_log(action, keyword, f"关键词 {action}: {keyword}", operator=operator)


def audit_refund_card(
    order_sn: str,
    *,
    shop_id: str = "",
    buyer_uid: str = "",
    success: bool = False,
    detail: str = "",
) -> None:
    audit_log(
        "refund_apply_card_send",
        order_sn,
        detail or ("发送成功" if success else "发送失败"),
        operator="system",
        severity="info" if success else "warn",
        extra={"shop_id": shop_id, "buyer_uid": buyer_uid, "api_success": success},
    )


def audit_config_change(section: str, keys: str, *, operator: str = "ui") -> None:
    audit_log("config_change", section, f"修改配置键: {keys}", operator=operator)


def audit_system_lifecycle(event: str, detail: str = "") -> None:
    audit_log(event, "application", detail or event, operator="system")
