"""
将 MMS latest_conversations 同步到本地 chat_sessions / chat_messages，
使软件 UI 与浏览器商家后台会话列表保持一致（双端展示）。
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Set

from bridge.context import ChannelType, Context, ContextType
from config import get_config
from utils.chat_time import naive_shanghai_from_unix_ts, shanghai_naive_now
from utils.logger_loguru import get_logger

_log = get_logger("MmsSessionSync")

_sync_lock = threading.Lock()
_last_msg_id_by_session: Dict[int, str] = {}


def mms_session_sync_enabled() -> bool:
    return bool(get_config("chat.mms_session_sync_enabled", True))


def _sync_page_size() -> int:
    try:
        n = int(get_config("chat.mms_session_sync_page_size", 50) or 50)
        return max(10, min(n, 100))
    except (TypeError, ValueError):
        return 50


def _should_enqueue_new() -> bool:
    return bool(get_config("chat.mms_session_sync_enqueue_new", True))


def _persist_session_row(
    *,
    account_id: int,
    platform_shop_id: str,
    account_name: str,
    item: Dict[str, Any],
) -> Optional[int]:
    from database.db_manager import db_manager

    buyer_uid = str(item.get("buyer_uid") or "")
    if not buyer_uid:
        return None

    sid = db_manager.get_or_create_chat_session(
        account_id=account_id,
        platform_shop_id=platform_shop_id,
        account_name=account_name,
        buyer_uid=buyer_uid,
        buyer_nickname=str(item.get("buyer_nickname") or "买家"),
    )

    preview = str(item.get("preview") or "")
    msg_id = item.get("msg_id")
    ts = float(item.get("ts") or 0)
    sent_at = naive_shanghai_from_unix_ts(ts) if ts > 0 else shanghai_naive_now()
    sender = str(item.get("sender_role") or "agent")
    sender_type = "customer" if sender == "customer" else "agent"

    from database.chat_persist import is_active_chat

    inc_unread = sender_type == "customer" and not is_active_chat(
        account_id, buyer_uid
    )
    mtype = item.get("msg_type")
    content_type = "text"
    if mtype in (1, "1"):
        content_type = "image"
        if not preview:
            preview = "[图片]"
    elif mtype in (14, "14"):
        content_type = "video"
        if not preview:
            preview = "[视频]"

    db_manager.add_chat_message(
        session_id=sid,
        account_id=account_id,
        sender_type=sender_type,
        content=preview,
        message_id=str(msg_id) if msg_id else None,
        content_type=content_type,
        increment_unread=inc_unread,
        sent_at=sent_at,
    )
    return sid


def _message_id_exists(session_id: int, msg_id: str) -> bool:
    from database.db_manager import db_manager
    from database.models import ChatMessage

    db = db_manager.get_session()
    try:
        ex = (
            db.query(ChatMessage.id)
            .filter(
                ChatMessage.session_id == int(session_id),
                ChatMessage.message_id == str(msg_id),
            )
            .first()
        )
        return ex is not None
    finally:
        db.close()


def _build_context_from_mms_item(
    item: Dict[str, Any],
    *,
    shop_id: str,
    user_id: str,
    username: str,
) -> Optional[Context]:
    raw = item.get("raw")
    if not isinstance(raw, dict):
        return None
    buyer_uid = str(item.get("buyer_uid") or "")
    if not buyer_uid:
        return None
    if str(item.get("sender_role") or "") != "customer":
        return None

    from bridge.context import PinduoduoKwargs

    preview = str(item.get("preview") or "")
    mtype = item.get("msg_type")
    try:
        mtype_i = int(mtype) if mtype is not None else 0
    except (TypeError, ValueError):
        mtype_i = 0

    if mtype_i == 1:
        ctype = ContextType.IMAGE
    elif mtype_i == 14:
        ctype = ContextType.VIDEO
    else:
        ctype = ContextType.TEXT

    kwargs = PinduoduoKwargs(
        from_user="user",
        to_user="mall_cs",
        from_uid=buyer_uid,
        to_uid=f"cs_{shop_id}_{user_id}",
        nickname=str(item.get("buyer_nickname") or "买家"),
        msg_id=str(item.get("msg_id") or "") or None,
        shop_id=str(shop_id),
        user_id=str(user_id),
        username=str(username),
        user_msg_type=ctype,
        raw_data={"message": raw, "source": "mms_session_sync"},
    )
    return Context(
        type=ctype,
        content=preview,
        channel_type=ChannelType.PINDUODUO,
        kwargs=kwargs,
    )


def _should_enqueue_polled_item(
    *,
    session_id: int,
    item: Dict[str, Any],
    existed_before: bool,
    reconnect_boost: bool = False,
) -> bool:
    msg_id = str(item.get("msg_id") or "")
    if not msg_id or str(item.get("sender_role") or "") != "customer":
        return False
    unread = int(item.get("unread_hint") or 0)
    prev = _last_msg_id_by_session.get(session_id)
    if prev is None:
        _last_msg_id_by_session[session_id] = msg_id
        if reconnect_boost:
            return unread > 0
        return unread > 0 and not existed_before
    if prev == msg_id:
        return False
    _last_msg_id_by_session[session_id] = msg_id
    return True


def _enqueue_new_buyer_message(
    *,
    item: Dict[str, Any],
    shop_id: str,
    user_id: str,
    username: str,
) -> None:
    context = _build_context_from_mms_item(
        item, shop_id=shop_id, user_id=user_id, username=username
    )
    if context is None:
        return

    from Channel.pinduoduo.ws_config import queue_name_for_account

    queue_name = queue_name_for_account(str(shop_id), str(user_id))

    async def _put() -> None:
        from Message import put_message

        await put_message(queue_name, context)

    try:
        import asyncio
        from ui.auto_reply_ui import auto_reply_manager

        target_loop = None
        for thread in auto_reply_manager.running_accounts.values():
            acc = getattr(thread, "account_data", None) or {}
            if (
                str(acc.get("shop_id") or "") == str(shop_id)
                and str(acc.get("user_id") or "") == str(user_id)
            ):
                target_loop = getattr(thread, "loop", None)
                break
        if target_loop is not None and target_loop.is_running():
            asyncio.run_coroutine_threadsafe(_put(), target_loop)
            return
        asyncio.run(_put())
    except Exception as e:
        _log.debug("MMS 轮询入队失败 buyer={}: {}", item.get("buyer_uid"), e)


def sync_mms_sessions_for_account(
    account_id: int, *, reconnect_boost: bool = False
) -> int:
    """
    拉取 MMS 会话列表并写入本地库。

    Returns:
        同步到的会话条数；失败返回 0。
    """
    if not mms_session_sync_enabled():
        return 0

    from database.db_manager import db_manager
    from Channel.pinduoduo.utils.API.get_messages import GetMessages

    row = db_manager.get_account_row_by_id(int(account_id))
    if not row:
        return 0

    shop_id = str(row.get("platform_shop_id") or "")
    user_id = str(row.get("seller_user_id") or "")
    channel_name = str(row.get("channel_name") or "pinduoduo")
    username = str(row.get("username") or "")

    acc = db_manager.get_account(channel_name, shop_id, user_id)
    if not acc or not acc.get("cookies"):
        return 0
    row = {**row, **acc}

    api = GetMessages(
        shop_id=shop_id,
        user_id=user_id,
        channel_name=channel_name,
        account_row=row,
    )
    sessions = api.get_all_sessions(page_size=_sync_page_size())
    if not sessions:
        return 0

    account_id_int = int(row["id"])
    synced = 0
    enqueue = _should_enqueue_new()

    for item in sessions:
        try:
            buyer_uid = str(item.get("buyer_uid") or "")
            if not buyer_uid:
                continue
            msg_id = str(item.get("msg_id") or "")
            sid_probe = db_manager.get_or_create_chat_session(
                account_id=account_id_int,
                platform_shop_id=shop_id,
                account_name=username,
                buyer_uid=buyer_uid,
                buyer_nickname=str(item.get("buyer_nickname") or "买家"),
            )
            existed_before = bool(msg_id and _message_id_exists(sid_probe, msg_id))
            sid = _persist_session_row(
                account_id=account_id_int,
                platform_shop_id=shop_id,
                account_name=username,
                item=item,
            )
            if sid is None:
                continue
            synced += 1
            if enqueue and _should_enqueue_polled_item(
                session_id=sid,
                item=item,
                existed_before=existed_before,
                reconnect_boost=reconnect_boost,
            ):
                _enqueue_new_buyer_message(
                    item=item,
                    shop_id=shop_id,
                    user_id=user_id,
                    username=username,
                )
        except Exception as e:
            _log.debug(
                "同步单条会话失败 account={} buyer={}: {}",
                account_id,
                item.get("buyer_uid"),
                e,
            )

    if synced:
        from utils.best_effort import run_best_effort

        def _refresh_hub() -> None:
            from ui.conversation_hub import get_conversation_hub, make_account_key

            key = make_account_key(channel_name, shop_id, username)
            hub = get_conversation_hub()
            hub.sync_latest_conversations(key, account_id_int)
            hub.list_changed.emit(key)

        run_best_effort(
            f"MMS Hub 刷新 account={account_id_int}",
            _refresh_hub,
            logger=_log,
        )

        _log.info(
            "MMS 会话同步完成: {} (shop={} 条数={})",
            username,
            shop_id,
            synced,
        )
    return synced


def list_account_ids_for_mms_sync() -> List[int]:
    """需要轮询 MMS 的账号：正在「开始回复」+ 配置的接待优先号（已上线）。"""
    from database.db_manager import db_manager

    ids: Set[int] = set()
    preferred = {
        str(x).strip()
        for x in (get_config("chat.preferred_transfer_seller_user_ids") or [])
        if str(x).strip()
    }

    try:
        from ui.auto_reply_ui import auto_reply_manager

        for thread in auto_reply_manager.running_accounts.values():
            acc = getattr(thread, "account_data", None) or {}
            aid = acc.get("id")
            if aid is not None:
                ids.add(int(aid))
    except Exception:
        pass

    for acc in db_manager.list_all_accounts_for_chat():
        uid = str(acc.get("seller_user_id") or "")
        if preferred and uid in preferred:
            ids.add(int(acc["id"]))
        elif not preferred and int(acc.get("status") or 0) == 1:
            ids.add(int(acc["id"]))

    return sorted(ids)


def sync_all_mms_sessions() -> int:
    """同步所有目标账号，返回总会话条数。"""
    if not mms_session_sync_enabled():
        return 0
    total = 0
    for aid in list_account_ids_for_mms_sync():
        with _sync_lock:
            try:
                total += sync_mms_sessions_for_account(aid)
            except Exception as e:
                _log.warning("MMS 会话同步失败 account_id={}: {}", aid, e)
    return total
