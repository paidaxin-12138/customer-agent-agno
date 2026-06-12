# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""处理器链内统一的 MMS 文本发送（asyncio.to_thread，避免阻塞事件循环）。"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Tuple

from bridge.context import Context
from utils.logger_loguru import get_logger

_logger = get_logger("ChannelSend")


def build_send_metadata(
    shop_id: Any,
    user_id: Any,
    from_uid: Any,
    *,
    channel_name: str = "pinduoduo",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if metadata:
        meta = dict(metadata)
        meta.setdefault("shop_id", str(shop_id))
        meta.setdefault("user_id", str(user_id))
        meta.setdefault("from_uid", str(from_uid))
        meta.setdefault("channel_name", channel_name)
        return meta
    return {
        "shop_id": str(shop_id),
        "user_id": str(user_id),
        "from_uid": str(from_uid),
        "channel_name": channel_name,
    }


def _resolve_outbox_ids(
    shop_id: Any,
    user_id: Any,
    from_uid: Any,
    *,
    context: Optional[Context] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[int], Optional[int], str, str]:
    """返回 (session_id, account_id, channel_name, login_username)。"""
    meta = metadata or {}
    channel_name = str(meta.get("channel_name") or "pinduoduo")
    login_username = str(meta.get("username") or meta.get("login_username") or "")
    session_id = meta.get("session_id")
    account_id = meta.get("account_id")
    try:
        if session_id is not None:
            session_id = int(session_id)
    except (TypeError, ValueError):
        session_id = None
    try:
        if account_id is not None:
            account_id = int(account_id)
    except (TypeError, ValueError):
        account_id = None

    if session_id is None:
        try:
            from database.session_store import resolve_session_id_from_context

            session_id = resolve_session_id_from_context(
                context, meta, allow_any_status=True
            )
        except Exception:
            session_id = None

    if account_id is None:
        try:
            from database.db_manager import db_manager

            acc = db_manager.get_account(
                channel_name, str(shop_id), str(user_id)
            )
            if acc and acc.get("id"):
                account_id = int(acc["id"])
                if not login_username:
                    login_username = str(acc.get("username") or "")
        except Exception:
            account_id = None

    if session_id is None and account_id and shop_id and user_id and from_uid:
        try:
            from database.db_manager import db_manager

            nick = str(
                meta.get("buyer_nickname")
                or meta.get("nickname")
                or "买家"
            )
            session_id = db_manager.get_or_create_chat_session(
                account_id=int(account_id),
                platform_shop_id=str(shop_id),
                account_name=login_username or str(meta.get("username") or ""),
                buyer_uid=str(from_uid),
                buyer_nickname=nick,
            )
            if session_id and metadata is not None:
                metadata["session_id"] = int(session_id)
        except Exception as e:
            _logger.debug("outbox ensure session 跳过: {}", e)

    return session_id, account_id, channel_name, login_username


def _prepare_outbox(
    shop_id: Any,
    user_id: Any,
    from_uid: Any,
    *,
    content: str,
    context: Optional[Context],
    metadata: Dict[str, Any],
    sender_type: str,
    message_kind: str = "text",
    payload: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    try:
        from database.outbound_outbox import create_pending, outbox_enabled

        if not outbox_enabled():
            return None
        sid, aid, ch, login_user = _resolve_outbox_ids(
            shop_id,
            user_id,
            from_uid,
            context=context,
            metadata=metadata,
        )
        st = str(metadata.get("_outbox_sender_type") or sender_type or "ai")
        if not (sid and aid):
            return None
        outbox_id = create_pending(
            session_id=int(sid),
            account_id=int(aid),
            channel_name=ch,
            shop_id=str(shop_id),
            user_id=str(user_id),
            buyer_uid=str(from_uid),
            content=str(content or "").strip(),
            sender_type=st,
            login_username=login_user,
            message_kind=message_kind,
            payload=payload,
        )
        if outbox_id:
            metadata["_outbound_outbox_id"] = outbox_id
        return outbox_id
    except Exception as e:
        _logger.debug("outbox create 跳过: {}", e)
        return None


def _claim_outbox_before_mms(outbox_id: Optional[int]) -> bool:
    """MMS 调用前 claim；失败时勿并发发送。"""
    if not outbox_id:
        return True
    try:
        from database.outbound_outbox import claim_for_send

        ok = claim_for_send(int(outbox_id))
        if not ok:
            _logger.warning("outbox claim 失败 id={}（可能并发处理中）", outbox_id)
        return bool(ok)
    except Exception as e:
        _logger.debug("outbox claim 异常 id={}: {}", outbox_id, e)
        return False


def _finalize_outbox_success(
    *,
    outbox_id: Optional[int],
    shop_id: Any,
    user_id: Any,
    from_uid: Any,
    body: str,
    meta: Dict[str, Any],
    context: Optional[Context],
    sender_type: str,
    notify_watchdog: bool,
    message_kind: str = "text",
    record_receipt: bool = True,
    mark_comfort_sent: bool = True,
) -> None:
    if mark_comfort_sent:
        meta["_outbound_comfort_sent"] = True

    chat_msg_id: Optional[int] = None
    if outbox_id and not meta.get("_outbox_skip_persist") and message_kind in (
        "text",
        "image",
    ):
        try:
            from utils.outbound_outbox_retry import _persist_outbox_content
            from database.outbound_outbox import get_row

            row = get_row(int(outbox_id)) or {
                "channel_name": meta.get("channel_name") or "pinduoduo",
                "shop_id": str(shop_id),
                "user_id": str(user_id),
                "buyer_uid": str(from_uid),
                "login_username": meta.get("username") or "",
                "content": body,
                "sender_type": meta.get("_outbox_sender_type") or sender_type,
                "message_kind": message_kind,
            }
            chat_msg_id = _persist_outbox_content(row)
        except Exception as e:
            _logger.debug("outbox persist after send: {}", e)

    if outbox_id:
        try:
            from database.outbound_outbox import mark_sent

            mark_sent(int(outbox_id), chat_message_id=chat_msg_id)
        except Exception as e:
            _logger.debug("outbox mark_sent: {}", e)

    if record_receipt:
        try:
            from Message.handlers.ai_reply_watchdog import resolve_session_key
            from utils.outbound_receipt import record_outbound_receipt

            send_meta = build_send_metadata(
                shop_id, user_id, from_uid, metadata=meta
            )
            session_key = resolve_session_key(context, send_meta)
            if session_key:
                record_outbound_receipt(
                    session_key,
                    buyer_uid=str(from_uid),
                    shop_id=str(shop_id),
                    user_id=str(user_id),
                    channel_name=str(send_meta.get("channel_name") or "pinduoduo"),
                )
        except Exception as e:
            _logger.debug("record_outbound_receipt: {}", e)

    if notify_watchdog:
        try:
            from Message.handlers.ai_reply_watchdog import notify_outbound_reply

            send_meta = build_send_metadata(
                shop_id, user_id, from_uid, metadata=meta
            )
            notify_outbound_reply(context, send_meta)
        except Exception as e:
            _logger.debug("notify_outbound_reply: {}", e)


async def send_structured_outbound(
    shop_id: Any,
    user_id: Any,
    from_uid: Any,
    *,
    content: str,
    message_kind: str = "text",
    payload: Optional[Dict[str, Any]] = None,
    context: Optional[Context] = None,
    metadata: Optional[Dict[str, Any]] = None,
    notify_watchdog: bool = True,
    sender_type: str = "ai",
) -> Tuple[bool, Any]:
    """结构化出站（文本/卡片等）；Outbox 先落库再 MMS。"""
    if not all([shop_id, user_id, from_uid]) or not str(content or "").strip():
        return False, None

    body = str(content).strip()
    meta = metadata if metadata is not None else {}
    outbox_id = _prepare_outbox(
        shop_id,
        user_id,
        from_uid,
        content=body,
        context=context,
        metadata=meta,
        sender_type=sender_type,
        message_kind=message_kind,
        payload=payload,
    )

    try:
        if outbox_id and not _claim_outbox_before_mms(outbox_id):
            from database.outbound_outbox import mark_failed

            mark_failed(int(outbox_id), "outbox_claim_failed")
            return False, {"success": False, "error_msg": "outbox_claim_failed"}
        from utils.outbound_mms_dispatch import execute_outbox_mms_send

        row = {
            "shop_id": str(shop_id),
            "user_id": str(user_id),
            "buyer_uid": str(from_uid),
            "content": body,
            "message_kind": message_kind,
            "payload_json": payload,
            "channel_name": meta.get("channel_name") or "pinduoduo",
        }
        ok, err = await asyncio.to_thread(execute_outbox_mms_send, row)
        if not ok:
            _logger.warning(
                "send_structured_outbound 失败 kind={}: {}",
                message_kind,
                err,
            )
            if outbox_id:
                from database.outbound_outbox import mark_failed

                mark_failed(int(outbox_id), err or "send_failed")
            return False, {"success": False, "error_msg": err}

        from utils.merchant_refund_apply_record import is_refund_gate_skip_error

        skipped_duplicate = (
            message_kind == "refund_apply_card" and is_refund_gate_skip_error(err)
        )
        if skipped_duplicate:
            _logger.info(
                "send_structured_outbound 退货卡跳过重复 buyer={} kind={}",
                from_uid,
                message_kind,
            )

        _finalize_outbox_success(
            outbox_id=outbox_id,
            shop_id=shop_id,
            user_id=user_id,
            from_uid=from_uid,
            body=body,
            meta=meta,
            context=context,
            sender_type=sender_type,
            notify_watchdog=notify_watchdog and not skipped_duplicate,
            message_kind=message_kind,
            record_receipt=not skipped_duplicate,
            mark_comfort_sent=not skipped_duplicate,
        )
        result: Dict[str, Any] = {"success": True, "skipped_duplicate": skipped_duplicate}
        if skipped_duplicate and isinstance(payload, dict):
            result["order_sn"] = payload.get("order_sn")
        return True, result
    except Exception as e:
        _logger.error("send_structured_outbound 异常 kind={}: {}", message_kind, e)
        if outbox_id:
            try:
                from database.outbound_outbox import mark_failed

                mark_failed(int(outbox_id), str(e))
            except Exception:
                pass
        return False, None


async def send_refund_apply_card_to_buyer(
    shop_id: Any,
    user_id: Any,
    from_uid: Any,
    *,
    order_sn: str,
    after_sales_type: int,
    question_type: int,
    refund_amount: int,
    message: Optional[str] = None,
    user_ship_status: int = 0,
    context: Optional[Context] = None,
    metadata: Optional[Dict[str, Any]] = None,
    notify_watchdog: bool = True,
) -> Tuple[bool, Any]:
    summary = (
        f"[refund_apply] order={order_sn} type={after_sales_type} "
        f"amount={refund_amount}"
    )
    payload = {
        "order_sn": str(order_sn),
        "after_sales_type": int(after_sales_type),
        "question_type": int(question_type),
        "refund_amount": int(refund_amount),
        "message": message or "",
        "user_ship_status": int(user_ship_status),
    }
    return await send_structured_outbound(
        shop_id,
        user_id,
        from_uid,
        content=summary,
        message_kind="refund_apply_card",
        payload=payload,
        context=context,
        metadata=metadata,
        notify_watchdog=notify_watchdog,
        sender_type="ai",
    )


async def send_image_to_buyer(
    shop_id: Any,
    user_id: Any,
    from_uid: Any,
    *,
    image_url: str,
    context: Optional[Context] = None,
    metadata: Optional[Dict[str, Any]] = None,
    notify_watchdog: bool = True,
    sender_type: str = "human",
) -> Tuple[bool, Any]:
    url = str(image_url or "").strip()
    if not url:
        return False, None
    summary = url if len(url) <= 120 else url[:120] + "…"
    return await send_structured_outbound(
        shop_id,
        user_id,
        from_uid,
        content=summary,
        message_kind="image",
        payload={"image_url": url},
        context=context,
        metadata=metadata,
        notify_watchdog=notify_watchdog,
        sender_type=sender_type,
    )


async def send_goods_card_to_buyer(
    shop_id: Any,
    user_id: Any,
    from_uid: Any,
    *,
    goods_id: int,
    biz_type: int = 2,
    context: Optional[Context] = None,
    metadata: Optional[Dict[str, Any]] = None,
    notify_watchdog: bool = True,
) -> Tuple[bool, Any]:
    summary = f"[goods_card] goods_id={int(goods_id)}"
    payload = {"goods_id": int(goods_id), "biz_type": int(biz_type)}
    return await send_structured_outbound(
        shop_id,
        user_id,
        from_uid,
        content=summary,
        message_kind="goods_card",
        payload=payload,
        context=context,
        metadata=metadata,
        notify_watchdog=notify_watchdog,
        sender_type="ai",
    )


def send_outbound_sync(
    shop_id: str,
    user_id: str,
    from_uid: str,
    *,
    content: str,
    message_kind: str = "text",
    payload: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    sender_type: str = "ai",
    notify_watchdog: bool = False,
    context: Optional[Context] = None,
) -> Tuple[bool, str]:
    """同步出站（UI 线程 / Agent 工具），带 Outbox。"""
    body = str(content or "").strip()
    if not all([shop_id, user_id, from_uid]) or not body:
        return False, "参数无效"
    meta = dict(metadata or {})
    meta.setdefault("shop_id", shop_id)
    meta.setdefault("user_id", user_id)
    meta.setdefault("from_uid", from_uid)
    meta.setdefault("_outbox_sender_type", sender_type)
    outbox_id = _prepare_outbox(
        shop_id,
        user_id,
        from_uid,
        content=body,
        context=context,
        metadata=meta,
        sender_type=sender_type,
        message_kind=message_kind,
        payload=payload,
    )
    row = {
        "shop_id": str(shop_id),
        "user_id": str(user_id),
        "buyer_uid": str(from_uid),
        "content": body,
        "message_kind": message_kind,
        "payload_json": payload,
        "channel_name": meta.get("channel_name") or "pinduoduo",
        "sender_type": sender_type,
        "login_username": meta.get("username") or meta.get("login_username") or "",
    }
    from utils.merchant_refund_apply_record import is_refund_gate_skip_error
    from utils.outbound_mms_dispatch import execute_outbox_mms_send

    if outbox_id and not _claim_outbox_before_mms(outbox_id):
        from database.outbound_outbox import mark_failed

        mark_failed(int(outbox_id), "outbox_claim_failed")
        return False, "outbox_claim_failed"
    ok, err = execute_outbox_mms_send(row)
    if not ok:
        if outbox_id:
            from database.outbound_outbox import mark_failed

            mark_failed(int(outbox_id), err or "send_failed")
        return False, err or "send_failed"
    skipped_duplicate = (
        message_kind == "refund_apply_card" and is_refund_gate_skip_error(err)
    )
    _finalize_outbox_success(
        outbox_id=outbox_id,
        shop_id=shop_id,
        user_id=user_id,
        from_uid=from_uid,
        body=body,
        meta=meta,
        context=context,
        sender_type=sender_type,
        notify_watchdog=notify_watchdog and not skipped_duplicate,
        message_kind=message_kind,
        record_receipt=not skipped_duplicate,
        mark_comfort_sent=not skipped_duplicate,
    )
    return True, ""


def send_goods_card_sync(
    shop_id: str,
    user_id: str,
    from_uid: str,
    *,
    goods_id: int,
    biz_type: int = 2,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """Agent 工具同步发卡（带 Outbox）。"""
    summary = f"[goods_card] goods_id={int(goods_id)}"
    payload = {"goods_id": int(goods_id), "biz_type": int(biz_type)}
    return send_outbound_sync(
        shop_id,
        user_id,
        from_uid,
        content=summary,
        message_kind="goods_card",
        payload=payload,
        metadata=metadata,
        sender_type="ai",
        notify_watchdog=False,
    )


def send_image_sync(
    shop_id: str,
    user_id: str,
    from_uid: str,
    *,
    image_url: str,
    metadata: Optional[Dict[str, Any]] = None,
    sender_type: str = "human",
    notify_watchdog: bool = False,
) -> Tuple[bool, str]:
    """同步发送图片（带 Outbox）。"""
    url = str(image_url or "").strip()
    if not url:
        return False, "图片地址为空"
    summary = url if len(url) <= 120 else url[:120] + "…"
    meta = dict(metadata or {})
    meta.setdefault("_outbox_sender_type", sender_type)
    return send_outbound_sync(
        shop_id,
        user_id,
        from_uid,
        content=summary,
        message_kind="image",
        payload={"image_url": url},
        metadata=meta,
        sender_type=sender_type,
        notify_watchdog=notify_watchdog,
    )


def send_human_text_sync(
    shop_id: str,
    user_id: str,
    from_uid: str,
    *,
    text: str,
    metadata: Optional[Dict[str, Any]] = None,
    notify_watchdog: bool = False,
) -> Tuple[bool, str]:
    """UI 人工文本发送（带 Outbox；落库仍由 Hub 负责时可设 _outbox_skip_persist）。"""
    meta = dict(metadata or {})
    meta.setdefault("_outbox_skip_persist", True)
    return send_outbound_sync(
        shop_id,
        user_id,
        from_uid,
        content=str(text or "").strip(),
        message_kind="text",
        metadata=meta,
        sender_type="human",
        notify_watchdog=notify_watchdog,
    )


async def send_text_to_buyer(
    shop_id: Any,
    user_id: Any,
    from_uid: Any,
    text: str,
    *,
    context: Optional[Context] = None,
    metadata: Optional[Dict[str, Any]] = None,
    notify_watchdog: bool = True,
    sender_type: str = "ai",
) -> bool:
    """向买家发送文本；Outbox：先 pending 再 MMS 再 sent/failed。"""
    if not all([shop_id, user_id, from_uid]) or not str(text or "").strip():
        return False

    meta = metadata if metadata is not None else {}
    meta.setdefault("_outbox_sender_type", sender_type)
    ok, _ = await send_structured_outbound(
        shop_id,
        user_id,
        from_uid,
        content=str(text).strip(),
        message_kind="text",
        context=context,
        metadata=meta,
        notify_watchdog=notify_watchdog,
        sender_type=sender_type,
    )
    return bool(ok)


def notify_outbound_from_metadata(
    context: Optional[Context] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """任意出站成功（含发卡等非文本）后通知 watchdog。"""
    try:
        from Message.handlers.ai_reply_watchdog import notify_outbound_reply

        notify_outbound_reply(context, metadata)
    except Exception as e:
        _logger.debug("notify_outbound_from_metadata: {}", e)


async def get_cs_list_async(shop_id: Any, user_id: Any) -> Optional[dict]:
    try:
        from Channel.pinduoduo.utils.API.send_message import SendMessage

        sender = SendMessage(str(shop_id), str(user_id))
        return await asyncio.to_thread(sender.getAssignCsList)
    except Exception as e:
        _logger.debug("get_cs_list_async: {}", e)
        return None


async def move_conversation_async(
    shop_id: Any, user_id: Any, from_uid: Any, cs_uid: str
) -> Optional[dict]:
    try:
        from Channel.pinduoduo.utils.API.send_message import SendMessage

        sender = SendMessage(str(shop_id), str(user_id))
        return await asyncio.to_thread(
            sender.move_conversation, str(from_uid), str(cs_uid)
        )
    except Exception as e:
        _logger.debug("move_conversation_async: {}", e)
        return None


async def transfer_to_available_cs_async(
    shop_id: Any,
    user_id: Any,
    from_uid: Any,
    *,
    exclude_self: bool = True,
    context: Optional[Context] = None,
    metadata: Optional[Dict[str, Any]] = None,
    notify_watchdog: bool = True,
) -> bool:
    """转接给可用客服：优先 config 中售后子账号，否则按负载最低。"""
    cs_list = await get_cs_list_async(shop_id, user_id)
    if not cs_list or not isinstance(cs_list, dict):
        return False
    from utils.pdd_transfer import pick_transfer_cs_uid

    cs_uid = pick_transfer_cs_uid(
        cs_list, str(shop_id), str(user_id), exclude_self=exclude_self
    )
    if not cs_uid:
        return False
    result = await move_conversation_async(shop_id, user_id, from_uid, cs_uid)
    if isinstance(result, dict) and bool(result.get("success")):
        if notify_watchdog and metadata is not None:
            metadata["_outbound_comfort_sent"] = True
            notify_outbound_from_metadata(context, metadata)
        try:
            from utils.session_human_lock import lock_session_to_human

            lock_session_to_human(
                context=context, metadata=metadata, reason="transfer_success"
            )
        except Exception as e:
            _logger.debug("transfer lock human: {}", e)
        return True
    return False

