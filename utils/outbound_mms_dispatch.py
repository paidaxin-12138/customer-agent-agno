"""Outbox 按 message_kind 分发 MMS 发送（同步）。"""
from __future__ import annotations

import json
from typing import Any, Dict, Tuple

from utils.logger_loguru import get_logger

_log = get_logger("OutboundMmsDispatch")


def _parse_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    raw = row.get("payload_json")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(str(raw))
        return data if isinstance(data, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _send_ok(result: Any) -> bool:
    return isinstance(result, dict) and result.get("success") is True


def _error_from_result(result: Any) -> str:
    if not isinstance(result, dict):
        return str(result or "send_failed")
    return str(
        result.get("errorMsg")
        or result.get("error_msg")
        or result.get("message")
        or result
    )


def execute_outbox_mms_send(row: Dict[str, Any]) -> Tuple[bool, str]:
    """
    根据 outbox 行执行 MMS 发送。
    返回 (success, error_detail)。
    """
    kind = str(row.get("message_kind") or "text").strip() or "text"
    shop_id = str(row.get("shop_id") or "")
    user_id = str(row.get("user_id") or "")
    buyer_uid = str(row.get("buyer_uid") or "")
    if not all([shop_id, user_id, buyer_uid]):
        return False, "缺少会话参数"

    try:
        from Channel.pinduoduo.utils.API.send_message import SendMessage

        sender = SendMessage(shop_id, user_id)
    except Exception as e:
        return False, str(e)

    payload = _parse_payload(row)

    try:
        if kind == "text":
            content = str(row.get("content") or "").strip()
            if not content:
                return False, "空文本"
            result = sender.send_text(buyer_uid, content)
            if _send_ok(result):
                return True, ""
            return False, _error_from_result(result)

        if kind == "refund_apply_card":
            order_sn = str(payload.get("order_sn") or "").strip()
            if not order_sn:
                return False, "缺少 order_sn"
            from utils.merchant_refund_apply_record import (
                REFUND_GATE_BLOCKED_PREFIX,
                REFUND_GATE_SKIP_PREFIX,
                RefundCardSendAction,
                evaluate_refund_card_send_gate,
                note_refund_card_mms_success,
            )

            gate_action = evaluate_refund_card_send_gate(
                shop_id, buyer_uid, order_sn
            )
            if gate_action == RefundCardSendAction.SKIP_ALREADY_SENT:
                _log.info(
                    "refund_apply_card 跳过重复发卡 shop={} buyer={} order={}",
                    shop_id,
                    buyer_uid,
                    order_sn,
                )
                return True, REFUND_GATE_SKIP_PREFIX
            if gate_action == RefundCardSendAction.BLOCK_EXPIRED:
                return False, f"{REFUND_GATE_BLOCKED_PREFIX}expired_or_failed"

            user_ship_status = int(payload.get("user_ship_status") or 0)
            after_sales_type = int(payload.get("after_sales_type") or 3)
            if user_ship_status == 0 and after_sales_type in (3, 4):
                after_sales_type = 1
            if user_ship_status == 0 or after_sales_type == 1:
                question_type = 0
            else:
                question_type = int(payload.get("question_type") or 1)

            result = sender.send_ask_refund_apply(
                order_sn,
                after_sales_type=after_sales_type,
                question_type=question_type,
                refund_amount=int(payload.get("refund_amount") or 0),
                message=payload.get("message") or None,
                user_ship_status=user_ship_status,
            )
            if _send_ok(result):
                note_refund_card_mms_success(
                    shop_id,
                    buyer_uid,
                    order_sn,
                    after_sales_type=after_sales_type,
                    refund_amount_fen=int(payload.get("refund_amount") or 0) or None,
                )
                return True, ""
            return False, _error_from_result(result)

        if kind == "goods_card":
            goods_id = payload.get("goods_id")
            if goods_id is None:
                return False, "缺少 goods_id"
            result = sender.send_mallGoodsCard(
                buyer_uid,
                int(goods_id),
                biz_type=int(payload.get("biz_type") or 2),
            )
            if _send_ok(result):
                return True, ""
            return False, _error_from_result(result)

        if kind == "image":
            image_url = str(
                payload.get("image_url") or row.get("content") or ""
            ).strip()
            if not image_url:
                return False, "缺少 image_url"
            result = sender.send_image(buyer_uid, image_url)
            if _send_ok(result):
                return True, ""
            return False, _error_from_result(result)

        return False, f"未知 message_kind: {kind}"
    except Exception as e:
        _log.warning("execute_outbox_mms_send kind={} 异常: {}", kind, e)
        return False, str(e)
