# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
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

def _pending_stub_sec() -> float:
    """send 成功但尚未收到 type=19 时，视为已提交的最长等待（秒）。"""
    try:
        raw = config.get("chat.after_sales_apply_pending_stub_sec")
        if raw is not None and str(raw).strip() != "":
            return max(120.0, min(float(raw), 172800.0))
    except (TypeError, ValueError):
        pass
    try:
        hours = int(config.get("chat.after_sales_apply_card_valid_hours", 48) or 48)
    except (TypeError, ValueError):
        hours = 48
    return max(120.0, min(float(max(1, hours)) * 3600.0, 172800.0))


class RefundApplyGate(str, Enum):
    SEND = "send"
    PENDING_NOTICE = "pending_notice"
    EXPIRED_NOTICE = "expired_notice"


class RefundCardSendAction(str, Enum):
    """退货卡 MMS 发送决策（含 outbox 重试）。"""

    SEND = "send"
    SKIP_ALREADY_SENT = "skip_already_sent"
    BLOCK_EXPIRED = "block_expired"


REFUND_GATE_BLOCKED_PREFIX = "refund_gate_blocked:"
REFUND_GATE_SKIP_PREFIX = "skipped:duplicate"


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
        age = now - _created_ts(row.get("created_at"))
        if age < _pending_stub_sec():
            return RefundApplyGate.PENDING_NOTICE
        db_manager.mark_refund_apply_expired(
            shop_id,
            order_sn,
            buyer_uid=row.get("buyer_uid"),
        )
        return RefundApplyGate.EXPIRED_NOTICE

    return RefundApplyGate.SEND


def gate_notice(gate: RefundApplyGate) -> str:
    if gate == RefundApplyGate.PENDING_NOTICE:
        return _pending_notice()
    if gate == RefundApplyGate.EXPIRED_NOTICE:
        return _expired_notice()
    return ""


def refund_card_action_notice(action: RefundCardSendAction) -> str:
    """evaluate_refund_card_send_gate 非 SEND 时的买家提示。"""
    if action == RefundCardSendAction.SKIP_ALREADY_SENT:
        return _pending_notice()
    if action == RefundCardSendAction.BLOCK_EXPIRED:
        return _expired_notice()
    return ""


def is_refund_gate_skip_error(err: Optional[str]) -> bool:
    return str(err or "") == REFUND_GATE_SKIP_PREFIX


def evaluate_refund_card_send_gate(
    shop_id: str,
    buyer_uid: str,
    order_sn: str,
) -> RefundCardSendAction:
    """
    退货卡发卡前检查（outbox 首发/重试共用）。

    同单重复代申请会导致平台下行 mstate=已过期，故 pending/内存已发须跳过。
    """
    sn = str(order_sn or "").strip()
    if not sn:
        return RefundCardSendAction.BLOCK_EXPIRED
    sid = str(shop_id or "")
    uid = str(buyer_uid or "")
    try:
        from utils.session_order_cache import has_sent_refund_card

        if has_sent_refund_card(sid, uid, sn):
            return RefundCardSendAction.SKIP_ALREADY_SENT
    except Exception:
        pass
    gate = check_refund_apply_gate(sid, sn)
    if gate == RefundApplyGate.SEND:
        return RefundCardSendAction.SEND
    if gate == RefundApplyGate.PENDING_NOTICE:
        return RefundCardSendAction.SKIP_ALREADY_SENT
    return RefundCardSendAction.BLOCK_EXPIRED


def note_refund_card_mms_success(
    shop_id: str,
    buyer_uid: str,
    order_sn: str,
    *,
    after_sales_type: Optional[int] = None,
    refund_amount_fen: Optional[int] = None,
) -> None:
    """MMS 发卡成功后立即记 pending，避免 outbox 重试连发同单。"""
    sn = str(order_sn or "").strip()
    if not sn:
        return
    sid = str(shop_id or "")
    uid = str(buyer_uid or "")
    try:
        from utils.session_order_cache import mark_refund_card_sent

        mark_refund_card_sent(sid, uid, sn)
    except Exception:
        pass
    if check_refund_apply_gate(sid, sn) != RefundApplyGate.SEND:
        return
    save_pending_after_send(
        sid,
        uid,
        sn,
        after_sales_type=after_sales_type,
        refund_amount_fen=refund_amount_fen,
    )


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
