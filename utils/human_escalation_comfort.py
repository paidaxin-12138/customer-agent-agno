# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""转人工/人工协助弹窗触发时的买家安抚话术（检测即发送，与弹窗操作解耦）。"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from bridge.context import Context
from config import config
from utils.logger_loguru import get_logger

_log = get_logger("HumanEscalationComfort")

_DEFAULT_NOTICE = "稍等下 这边上报一下呢亲亲"

# 弹窗关闭时若尚未出站安抚，可补发（media_human 等已有专用话术）
_DIALOG_COMFORT_REASONS = frozenset(
    {
        "keyword_human",
        "ai_failed",
        "ai_timeout",
        "queue_degrade",
        "order_address_change",
        "order_modify",
        "buyer_emotion_escalate",
    }
)


def human_transfer_comfort_notice() -> str:
    custom = str(config.get("chat.human_transfer_notice") or "").strip()
    return custom if custom else _DEFAULT_NOTICE


def resolve_session_ids(
    context: Optional[Context] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """从 metadata / context.kwargs 解析 shop_id、user_id、from_uid。"""
    meta = metadata or {}
    shop_id = meta.get("shop_id")
    user_id = meta.get("user_id")
    from_uid = meta.get("from_uid")
    if context is not None:
        ku = getattr(context, "kwargs", None)
        if ku is not None:
            if not shop_id:
                shop_id = ku.get("shop_id") if isinstance(ku, dict) else getattr(ku, "shop_id", None)
            if not user_id:
                user_id = ku.get("user_id") if isinstance(ku, dict) else getattr(ku, "user_id", None)
            if not from_uid:
                from_uid = ku.get("from_uid") if isinstance(ku, dict) else getattr(ku, "from_uid", None)
    if not from_uid and context is not None:
        try:
            from ui.conversation_hub import parse_peer_from_context

            uid2, _ = parse_peer_from_context(context)
            if uid2:
                from_uid = uid2
        except Exception:
            pass
    return (
        str(shop_id) if shop_id else None,
        str(user_id) if user_id else None,
        str(from_uid) if from_uid else None,
    )


async def send_human_transfer_comfort(
    context: Optional[Context],
    metadata: Optional[Dict[str, Any]],
    *,
    reason: str = "",
) -> bool:
    """检测到转人工需求时立即向买家发送安抚语；已发送则跳过。"""
    meta = metadata if metadata is not None else {}
    if meta.get("_outbound_comfort_sent"):
        return False
    shop_id, user_id, from_uid = resolve_session_ids(context, meta)
    if not all([shop_id, user_id, from_uid]):
        _log.debug(
            "转人工安抚跳过：缺少会话 ID (reason={} shop={} user={} buyer={})",
            reason,
            shop_id,
            user_id,
            from_uid,
        )
        return False
    notice = human_transfer_comfort_notice()
    try:
        from Message.handlers.channel_send import send_text_to_buyer

        ok = await send_text_to_buyer(
            shop_id,
            user_id,
            from_uid,
            notice,
            context=context,
            metadata=meta,
        )
        if ok:
            _log.info("转人工安抚已发送: reason={} buyer={}", reason, from_uid)
        return ok
    except Exception as e:
        _log.warning("转人工安抚发送失败: reason={} err={}", reason, e)
        return False


def should_send_dialog_comfort_on_dismiss(reason: str) -> bool:
    return str(reason or "") in _DIALOG_COMFORT_REASONS


def send_human_transfer_comfort_from_payload(payload: Dict[str, Any]) -> bool:
    """弹窗关闭/取消时的同步补发（仅当 handler 层未成功发送时）。"""
    if payload.get("comfort_sent"):
        return False
    reason = str(payload.get("reason") or "")
    if not should_send_dialog_comfort_on_dismiss(reason):
        return False
    shop_id = str(
        payload.get("platform_shop_id") or payload.get("shop_id") or ""
    ).strip()
    user_id = str(payload.get("seller_user_id") or "").strip()
    buyer_uid = str(payload.get("buyer_uid") or "").strip()
    if not all([shop_id, user_id, buyer_uid]):
        return False
    notice = human_transfer_comfort_notice()
    try:
        from Channel.pinduoduo.utils.API.send_message import SendMessage

        sender = SendMessage(shop_id, user_id)
        result = sender.send_text(buyer_uid, notice)
        if isinstance(result, dict) and result.get("success"):
            _log.info(
                "弹窗关闭补发转人工安抚: reason={} buyer={}",
                reason,
                buyer_uid,
            )
            return True
        _log.warning("弹窗关闭补发安抚失败: {}", result)
        return False
    except Exception as e:
        _log.warning("弹窗关闭补发安抚异常: {}", e)
        return False
