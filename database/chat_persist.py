"""
将进线 / 人工 / AI 消息写入 chat_sessions / chat_messages，并维护未读数。

会话摘要与未读数以 SQLite 为准；UI 索引通过 ``database.session_store.sync_hub_session`` 刷新。
"""
from __future__ import annotations

import threading
from typing import Any, Optional, Tuple

from bridge.context import ContextType
from utils.chat_time import naive_shanghai_from_unix_ts, shanghai_naive_now
from utils.logger_loguru import get_logger

_log = get_logger("chat_persist")

_active_lock = threading.Lock()
_active: Optional[Tuple[int, str]] = None


def set_active_chat_session(account_id: Optional[int], buyer_uid: Optional[str]) -> None:
    """当前用户在「实时聊天」中选中的会话；用于判断是否增加未读。"""
    global _active
    with _active_lock:
        if account_id is None or buyer_uid is None:
            _active = None
        else:
            _active = (account_id, str(buyer_uid))


def is_active_chat(account_id: int, buyer_uid: str) -> bool:
    with _active_lock:
        return _active == (account_id, str(buyer_uid))


def _preview_for_hub(text: str) -> str:
    t = str(text or "")
    return t[:50] + ("…" if len(t) > 50 else "")


def _sync_hub_after_outbound(
    channel_name: str,
    platform_shop_id: str,
    seller_user_id: str,
    login_username: str,
    buyer_uid: str,
    text: str,
    *,
    role: str,
) -> None:
    """出站消息落库后刷新 Hub（AI / 人工等不经 record_from_context 的路径）。"""
    try:
        from ui.conversation_hub import get_conversation_hub

        get_conversation_hub().notify_persisted_message(
            channel_name,
            platform_shop_id,
            seller_user_id,
            login_username,
            buyer_uid,
            _preview_for_hub(text),
            role=role,
        )
    except Exception as exc:
        _log.debug("hub sync 跳过 role={}: {}", role, exc)


def _normalize_message_id(message_id: Optional[str]) -> Optional[str]:
    if message_id is None or message_id == "":
        return None
    return message_id


def _sent_at_from_ts(ts: float):
    return naive_shanghai_from_unix_ts(ts) if ts else shanghai_naive_now()


def _ensure_chat_session(
    channel_name: str,
    platform_shop_id: str,
    seller_user_id: str,
    login_username: str,
    buyer_uid: str,
    buyer_nickname: str = "买家",
) -> tuple[Optional[int], Optional[int]]:
    """解析账号并 get_or_create 会话，返回 (account_id, session_id)。"""
    from database.db_manager import db_manager

    acc = db_manager.get_account(channel_name, platform_shop_id, seller_user_id)
    if not acc or not acc.get("id"):
        return None, None
    account_id = int(acc["id"])
    sid = db_manager.get_or_create_chat_session(
        account_id=account_id,
        platform_shop_id=platform_shop_id,
        account_name=login_username,
        buyer_uid=buyer_uid,
        buyer_nickname=buyer_nickname or "买家",
    )
    return account_id, sid


def split_chat_body_for_storage(context: Any, preview: str) -> Tuple[str, str, Optional[str]]:
    """
    根据 Context 与拼多多 raw_data 得到 (content_type, content 列, image_url)。
    用于买家图片/视频，以及 mall_cs 侧（手机客服）发送的图片/视频。
    """
    raw = getattr(context, "raw_data", None)
    mtype = None
    if isinstance(raw, dict):
        msg = raw.get("message")
        if isinstance(msg, dict):
            mtype = msg.get("type")
    ctype = getattr(context, "type", None)
    body = getattr(context, "content", None)
    url: Optional[str] = None
    if isinstance(body, str) and body.strip().startswith(("http://", "https://")):
        url = body.strip()

    if ctype == ContextType.IMAGE or mtype == 1:
        if url:
            return "image", "[图片]", url
        return "image", (preview or "[图片]").strip() or "[图片]", None
    if ctype == ContextType.VIDEO or mtype == 14:
        if url:
            return "video", "[视频]", url
        return "video", (preview or "[视频]").strip() or "[视频]", None

    if ctype == ContextType.MALL_CS and mtype == 1:
        if url:
            return "image", "[图片]", url
        return "image", (preview or "[图片]").strip() or "[图片]", None
    if ctype == ContextType.MALL_CS and mtype == 14:
        if url:
            return "video", "[视频]", url
        return "video", (preview or "[视频]").strip() or "[视频]", None

    return "text", preview or (str(body) if body is not None else ""), None


def persist_customer_from_context(
    channel_name: str,
    platform_shop_id: str,
    seller_user_id: str,
    login_username: str,
    buyer_uid: str,
    buyer_nickname: str,
    preview: str,
    message_id: Optional[str],
    ts: float,
    context: Optional[Any] = None,
) -> Optional[int]:
    account_id, sid = _ensure_chat_session(
        channel_name,
        platform_shop_id,
        seller_user_id,
        login_username,
        buyer_uid,
        buyer_nickname,
    )
    if account_id is None or sid is None:
        return None
    from database.db_manager import db_manager

    st = _sent_at_from_ts(ts)
    inc = not is_active_chat(account_id, buyer_uid)
    mid = _normalize_message_id(message_id)
    if context is not None:
        ct, row_content, img = split_chat_body_for_storage(context, preview)
    else:
        ct, row_content, img = "text", preview or "", None
    db_manager.add_chat_message(
        session_id=sid,
        account_id=account_id,
        sender_type="customer",
        content=row_content or "",
        message_id=mid,
        content_type=ct,
        image_url=img,
        increment_unread=inc,
        sent_at=st,
    )
    return sid


def persist_platform_civility_from_context(
    channel_name: str,
    platform_shop_id: str,
    seller_user_id: str,
    login_username: str,
    buyer_uid: str,
    buyer_nickname: str,
    preview: str,
    message_id: Optional[str],
    ts: float,
) -> Optional[int]:
    """平台自动文明提示：sender_type=system，不计为有效出站回复。"""
    account_id, sid = _ensure_chat_session(
        channel_name,
        platform_shop_id,
        seller_user_id,
        login_username,
        buyer_uid,
        buyer_nickname,
    )
    if account_id is None or sid is None:
        return None
    from database.db_manager import db_manager

    sent = _sent_at_from_ts(ts)
    mid = _normalize_message_id(message_id)
    db_manager.add_chat_message(
        session_id=sid,
        account_id=account_id,
        sender_type="system",
        content=preview or "",
        message_id=mid,
        content_type="text",
        image_url=None,
        increment_unread=False,
        sent_at=sent,
    )
    return sid


def persist_inbound_transfer_from_context(
    channel_name: str,
    platform_shop_id: str,
    seller_user_id: str,
    login_username: str,
    buyer_uid: str,
    buyer_nickname: str,
    preview: str,
    message_id: Optional[str],
    ts: float,
) -> Optional[int]:
    """外部/售前转接进线：系统提示 + 标记已转接（截流由 apply_inbound_transfer_takeover 执行）。"""
    account_id, sid = _ensure_chat_session(
        channel_name,
        platform_shop_id,
        seller_user_id,
        login_username,
        buyer_uid,
        buyer_nickname,
    )
    if account_id is None or sid is None:
        return None
    from database.db_manager import db_manager

    sent = _sent_at_from_ts(ts)
    mid = _normalize_message_id(message_id)
    inc = not is_active_chat(account_id, buyer_uid)
    db_manager.add_chat_message(
        session_id=sid,
        account_id=account_id,
        sender_type="system",
        content=preview or "[会话已转接]",
        message_id=mid,
        content_type="text",
        image_url=None,
        increment_unread=inc,
        sent_at=sent,
    )
    try:
        from utils.inbound_transfer_gate import mark_inbound_transferred

        mark_inbound_transferred(sid)
    except Exception as e:
        _log.debug("转接标记 inbound_transferred 失败: {}", e)
    return sid


def persist_seller_mall_cs_from_context(
    channel_name: str,
    platform_shop_id: str,
    seller_user_id: str,
    login_username: str,
    buyer_uid: str,
    buyer_nickname: str,
    context: Any,
    preview: str,
    message_id: Optional[str],
    ts: float,
) -> Optional[int]:
    """手机端 / 其他客户端以 mall_cs 身份发送的消息，写入 human 侧记录。"""
    from utils.platform_system_msg import is_platform_civility_message

    if is_platform_civility_message(context):
        return persist_platform_civility_from_context(
            channel_name,
            platform_shop_id,
            seller_user_id,
            login_username,
            buyer_uid,
            buyer_nickname,
            preview,
            message_id,
            ts,
        )
    account_id, sid = _ensure_chat_session(
        channel_name,
        platform_shop_id,
        seller_user_id,
        login_username,
        buyer_uid,
        buyer_nickname,
    )
    if account_id is None or sid is None:
        return None
    from database.db_manager import db_manager

    sent = _sent_at_from_ts(ts)
    mid = _normalize_message_id(message_id)
    ct, row_content, img = split_chat_body_for_storage(context, preview)
    db_manager.add_chat_message(
        session_id=sid,
        account_id=account_id,
        sender_type="human",
        content=row_content or preview or "",
        message_id=mid,
        content_type=ct,
        image_url=img,
        increment_unread=False,
        sent_at=sent,
    )
    return sid


def persist_human_message(
    channel_name: str,
    platform_shop_id: str,
    seller_user_id: str,
    login_username: str,
    buyer_uid: str,
    text: str,
) -> Optional[int]:
    account_id, sid = _ensure_chat_session(
        channel_name,
        platform_shop_id,
        seller_user_id,
        login_username,
        buyer_uid,
    )
    if account_id is None or sid is None:
        return None
    from database.db_manager import db_manager

    db_manager.add_chat_message(
        session_id=sid,
        account_id=account_id,
        sender_type="human",
        content=text,
        message_id=None,
        increment_unread=False,
        sent_at=shanghai_naive_now(),
    )
    _sync_hub_after_outbound(
        channel_name,
        platform_shop_id,
        seller_user_id,
        login_username,
        buyer_uid,
        text,
        role="agent",
    )
    return sid


def persist_escalation_system_note(payload: dict, note: str) -> None:
    """写入一条系统提示，便于聊天窗口展示转人工/求助记录。"""
    from database.db_manager import db_manager

    try:
        aid = int(payload["account_id"])
        sid = db_manager.get_or_create_chat_session(
            account_id=aid,
            platform_shop_id=str(payload["platform_shop_id"]),
            account_name=str(payload["login_username"]),
            buyer_uid=str(payload["buyer_uid"]),
            buyer_nickname=str(payload.get("buyer_nickname") or "买家"),
        )
        from database.session_store import set_ai_mode

        set_ai_mode(sid, False)
        db_manager.add_chat_message(
            session_id=sid,
            account_id=aid,
            sender_type="system",
            content=note,
            message_id=None,
            increment_unread=False,
            sent_at=shanghai_naive_now(),
        )
    except Exception as e:
        _log.warning("persist_escalation_system_note 失败: {}", e)


def persist_ai_message(
    channel_name: str,
    platform_shop_id: str,
    seller_user_id: str,
    login_username: str,
    buyer_uid: str,
    text: str,
) -> Optional[int]:
    account_id, sid = _ensure_chat_session(
        channel_name,
        platform_shop_id,
        seller_user_id,
        login_username,
        buyer_uid,
    )
    if account_id is None or sid is None:
        return None
    from database.db_manager import db_manager

    db_manager.add_chat_message(
        session_id=sid,
        account_id=account_id,
        sender_type="ai",
        content=text,
        message_id=None,
        increment_unread=False,
        sent_at=shanghai_naive_now(),
    )
    _sync_hub_after_outbound(
        channel_name,
        platform_shop_id,
        seller_user_id,
        login_username,
        buyer_uid,
        text,
        role="ai",
    )
    return sid
