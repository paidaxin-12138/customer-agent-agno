"""
商家代消费者申请快捷退款：订单级状态（pending / expired / failed）与发卡前检查。
"""

from __future__ import annotations

import time
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from config import config
from database.db_manager import db_manager

STATUS_PENDING = "pending"
STATUS_EXPIRED = "expired"
STATUS_FAILED = "failed"

# send 成功但尚未收到 type=19 时，短时内视为已提交，避免连发
_PENDING_STUB_SEC = 120


class RefundApplyGate(str, Enum):
    SEND = "send"
    PENDING_NOTICE = "pending_notice"
    EXPIRED_NOTICE = "expired_notice"


def _pending_notice() -> str:
    return str(
        config.get(
            "chat.after_sales_apply_pending_notice",
            "亲，已经为您提交了退款申请，请耐心等待。",
        )
    )


def _expired_notice() -> str:
    return str(
        config.get(
            "chat.after_sales_apply_record_expired_notice",
            "亲，该订单的快捷退款申请已超时。请到拼多多APP订单详情页点击「申请售后」"
            "手动操作，或回复「人工」。",
        )
    )


def _created_ts(created_at: Any) -> float:
    if isinstance(created_at, datetime):
        return created_at.timestamp()
    return time.time()


def check_refund_apply_gate(shop_id: str, order_sn: str) -> RefundApplyGate:
    """
    发卡前检查该 order_sn 最近一条记录。
    pending 且 now < valid_time → 不再发卡；
    expired / failed（或 pending 已过 valid_time）→ 不再发卡。
    """
    row = db_manager.get_latest_refund_apply_for_order(shop_id, order_sn)
    if not row:
        return RefundApplyGate.SEND

    status = (row.get("status") or "").strip().lower()
    now = time.time()
    vt = row.get("valid_time_unix")

    if row.get("api_success") is False:
        return RefundApplyGate.EXPIRED_NOTICE
    if row.get("card_expired") is True:
        return RefundApplyGate.EXPIRED_NOTICE

    if status in (STATUS_EXPIRED, STATUS_FAILED):
        return RefundApplyGate.EXPIRED_NOTICE

    if status == STATUS_PENDING:
        if vt and now < float(vt):
            return RefundApplyGate.PENDING_NOTICE
        if vt and now >= float(vt):
            db_manager.mark_refund_apply_expired(
                shop_id,
                order_sn,
                buyer_uid=row.get("buyer_uid"),
            )
            return RefundApplyGate.EXPIRED_NOTICE
        # 已 send、尚未收到 type=19 的 valid_time
        if now - _created_ts(row.get("created_at")) < _PENDING_STUB_SEC:
            return RefundApplyGate.PENDING_NOTICE

    return RefundApplyGate.SEND


def gate_notice(gate: RefundApplyGate) -> str:
    if gate == RefundApplyGate.PENDING_NOTICE:
        return _pending_notice()
    if gate == RefundApplyGate.EXPIRED_NOTICE:
        return _expired_notice()
    return ""


def save_pending_after_send(
    shop_id: str,
    buyer_uid: str,
    order_sn: str,
    *,
    after_sales_type: Optional[int] = None,
    refund_amount_fen: Optional[int] = None,
) -> int:
    """MMS send 成功：先记 pending（valid_time 待 type=19 补全）。"""
    return db_manager.record_merchant_refund_apply(
        shop_id,
        buyer_uid,
        order_sn,
        api_success=True,
        status=STATUS_PENDING,
        after_sales_type=after_sales_type,
        refund_amount_fen=refund_amount_fen,
    )


def save_failed_apply(
    shop_id: str,
    buyer_uid: str,
    order_sn: str,
    *,
    error_msg: Optional[str] = None,
    after_sales_type: Optional[int] = None,
    refund_amount_fen: Optional[int] = None,
) -> int:
    return db_manager.record_merchant_refund_apply(
        shop_id,
        buyer_uid,
        order_sn,
        api_success=False,
        status=STATUS_FAILED,
        error_msg=error_msg,
        after_sales_type=after_sales_type,
        refund_amount_fen=refund_amount_fen,
    )


def update_apply_from_card_push(
    shop_id: str,
    buyer_uid: str,
    order_sn: str,
    *,
    card_msg_id: Optional[str],
    valid_time_unix: Optional[int],
    card_expired: bool,
) -> bool:
    return db_manager.update_refund_apply_from_card_push(
        shop_id,
        buyer_uid,
        order_sn,
        card_msg_id=card_msg_id,
        valid_time_unix=valid_time_unix,
        card_expired=card_expired,
    )


def mark_apply_expired(
    shop_id: str,
    order_sn: str,
    *,
    buyer_uid: Optional[str] = None,
    card_msg_id: Optional[str] = None,
) -> bool:
    return db_manager.mark_refund_apply_expired(
        shop_id,
        order_sn,
        buyer_uid=buyer_uid,
        card_msg_id=card_msg_id,
    )


def format_apply_counts_log(
    *,
    order_sn: str,
    buyer_uid: str,
    api_success: bool,
    record_id: int,
    counts: Dict[str, int],
    card_expired: Optional[bool] = None,
) -> str:
    parts = [
        f"代申请退款统计 order_sn={order_sn} buyer={buyer_uid}",
        f"本单成功={counts.get('order_total', 0)}",
        f"今日该买家={counts.get('buyer_today', 0)}",
        f"今日全店={counts.get('shop_today', 0)}",
        f"api_success={api_success}",
        f"record_id={record_id}",
    ]
    if counts.get("order_attempts") is not None:
        parts.append(f"本单尝试={counts['order_attempts']}")
    if card_expired is not None:
        parts.append(f"card_expired={card_expired}")
    return " ".join(parts)


def get_apply_counts(shop_id: str, buyer_uid: str, order_sn: str) -> Dict[str, int]:
    return db_manager.merchant_refund_apply_counts(shop_id, buyer_uid, order_sn)


# 兼容旧 import
def record_apply_attempt(
    shop_id: str,
    buyer_uid: str,
    order_sn: str,
    *,
    api_success: bool,
    after_sales_type: Optional[int] = None,
    refund_amount_fen: Optional[int] = None,
    error_msg: Optional[str] = None,
) -> Dict[str, Any]:
    if api_success:
        record_id = save_pending_after_send(
            shop_id,
            buyer_uid,
            order_sn,
            after_sales_type=after_sales_type,
            refund_amount_fen=refund_amount_fen,
        )
    else:
        record_id = save_failed_apply(
            shop_id,
            buyer_uid,
            order_sn,
            error_msg=error_msg,
            after_sales_type=after_sales_type,
            refund_amount_fen=refund_amount_fen,
        )
    counts = db_manager.merchant_refund_apply_counts(shop_id, buyer_uid, order_sn)
    summary = format_apply_counts_log(
        order_sn=order_sn,
        buyer_uid=buyer_uid,
        api_success=api_success,
        record_id=record_id,
        counts=counts,
    )
    return {"record_id": record_id, "counts": counts, "summary": summary}


def update_apply_card_outcome(
    shop_id: str,
    buyer_uid: str,
    order_sn: str,
    *,
    card_expired: bool,
    card_msg_id: Optional[str] = None,
    valid_time_unix: Optional[int] = None,
) -> bool:
    vt: Optional[int] = valid_time_unix
    if vt is None and card_msg_id:
        row = db_manager.get_latest_refund_apply_for_order(shop_id, order_sn)
        if row:
            vt = row.get("valid_time_unix")
    return update_apply_from_card_push(
        shop_id,
        buyer_uid,
        order_sn,
        card_msg_id=card_msg_id,
        valid_time_unix=vt,
        card_expired=card_expired,
    )
