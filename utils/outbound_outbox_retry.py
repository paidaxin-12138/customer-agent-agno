"""Outbox 重试发送（仅重发 MMS，不重新生成）。"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from utils.logger_loguru import get_logger

_log = get_logger("OutboundOutboxRetry")


def _session_key_from_row(row: Dict[str, Any]) -> str:
    from Message.handlers.ai_reply_watchdog import resolve_session_key

    return (
        resolve_session_key(
            metadata={
                "channel_name": row.get("channel_name") or "pinduoduo",
                "shop_id": str(row.get("shop_id") or ""),
                "user_id": str(row.get("user_id") or ""),
                "from_uid": str(row.get("buyer_uid") or ""),
            }
        )
        or ""
    )


def _persist_outbox_content(row: Dict[str, Any]) -> Optional[int]:
    """将已发送内容写入 chat_messages（若尚未存在）。"""
    sender = str(row.get("sender_type") or "ai")
    kind = str(row.get("message_kind") or "text").strip() or "text"
    ch = str(row.get("channel_name") or "pinduoduo")
    shop = str(row.get("shop_id") or "")
    user = str(row.get("user_id") or "")
    login = str(row.get("login_username") or "")
    buyer = str(row.get("buyer_uid") or "")
    try:
        from database.chat_persist import (
            persist_ai_message,
            persist_human_image_message,
            persist_human_message,
        )

        if kind == "image":
            import json

            payload = row.get("payload_json")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, json.JSONDecodeError):
                    payload = {}
            if not isinstance(payload, dict):
                payload = {}
            image_url = str(
                payload.get("image_url") or row.get("content") or ""
            ).strip()
            if not image_url:
                return None
            return persist_human_image_message(
                ch, shop, user, login, buyer, image_url
            )
        if sender == "human":
            return persist_human_message(
                ch, shop, user, login, buyer, str(row.get("content") or "")
            )
        return persist_ai_message(
            str(row.get("channel_name") or "pinduoduo"),
            str(row.get("shop_id") or ""),
            str(row.get("user_id") or ""),
            str(row.get("login_username") or ""),
            str(row.get("buyer_uid") or ""),
            str(row.get("content") or ""),
        )
    except Exception as e:
        _log.debug("outbox persist 跳过: {}", e)
        return None


def retry_outbox_row_sync(row: Dict[str, Any]) -> bool:
    """同步重试单条 outbox；成功返回 True。"""
    from database.outbound_outbox import (
        claim_for_send,
        mark_failed,
        mark_sent,
        outbox_enabled,
    )

    if not outbox_enabled():
        return False
    oid = int(row.get("id") or 0)
    if not oid:
        return False
    if not claim_for_send(oid):
        return False

    session_key = _session_key_from_row(row)
    kind = str(row.get("message_kind") or "text").strip() or "text"
    # 结构化卡片（退货卡/商品卡）须走 execute + 订单级门禁，不能因同会话文本回执而跳过。
    if kind in ("text", "image"):
        try:
            from utils.outbound_receipt import has_recent_outbound_receipt

            if session_key and has_recent_outbound_receipt(
                session_key, within_sec=21600.0
            ):
                _log.info(
                    "outbox 重试跳过 MMS（已有出站回执）id={} buyer={} kind={}",
                    oid,
                    row.get("buyer_uid"),
                    kind,
                )
                msg_id = _persist_outbox_content(row)
                mark_sent(oid, chat_message_id=msg_id)
                return True
        except Exception as e:
            _log.debug("outbox receipt 检查: {}", e)

    shop_id = str(row.get("shop_id") or "")
    user_id = str(row.get("user_id") or "")
    buyer_uid = str(row.get("buyer_uid") or "")
    content = str(row.get("content") or "").strip()
    if not all([shop_id, user_id, buyer_uid]):
        mark_failed(oid, "缺少会话参数")
        return False
    if kind == "text" and not content:
        mark_failed(oid, "空文本")
        return False

    try:
        from utils.outbound_mms_dispatch import execute_outbox_mms_send

        ok, err = execute_outbox_mms_send(row)
        if not ok and err.startswith("refund_gate_blocked:"):
            from database.outbound_outbox import mark_abandoned

            mark_abandoned(oid, err)
            _log.info(
                "outbox 退货卡门禁放弃 id={} order_gate={} buyer={}",
                oid,
                err,
                buyer_uid,
            )
            return False
        if ok:
            from utils.merchant_refund_apply_record import is_refund_gate_skip_error

            if not is_refund_gate_skip_error(err):
                try:
                    from utils.outbound_receipt import record_outbound_receipt

                    if session_key:
                        record_outbound_receipt(
                            session_key,
                            buyer_uid=buyer_uid,
                            shop_id=shop_id,
                            user_id=user_id,
                            channel_name=str(row.get("channel_name") or "pinduoduo"),
                        )
                except Exception:
                    pass
            msg_id = None
            if kind in ("text", "image"):
                msg_id = _persist_outbox_content(row)
            mark_sent(oid, chat_message_id=msg_id)
            _log.info(
                "outbox 重试发送成功 id={} kind={} buyer={}",
                oid,
                kind,
                buyer_uid,
            )
            return True
        mark_failed(oid, err or "send_failed")
        return False
    except Exception as e:
        mark_failed(oid, str(e))
        _log.warning("outbox 重试异常 id={}: {}", oid, e)
        return False


def retry_outbox_for_account_sync(
    *,
    account_id: int,
    limit: int = 10,
) -> int:
    """同步重试某账号下 due 的 outbox 记录，返回成功条数。"""
    from database.outbound_outbox import fetch_due_retries, outbox_enabled

    if not outbox_enabled():
        return 0
    rows = fetch_due_retries(account_id=int(account_id), limit=limit)
    ok_count = 0
    for row in rows:
        if retry_outbox_row_sync(row):
            ok_count += 1
    return ok_count


async def retry_outbox_for_account(
    *,
    account_id: int,
    limit: int = 10,
) -> int:
    return await asyncio.to_thread(
        retry_outbox_for_account_sync,
        account_id=account_id,
        limit=limit,
    )
