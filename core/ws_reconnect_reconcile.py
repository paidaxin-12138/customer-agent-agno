# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
WebSocket 认证成功（含重连）后的消息补偿：MMS 轮询同步 + 未回复买家消息重新入队。
"""
from __future__ import annotations

import hashlib
import threading
import time
from typing import Any, Dict, Optional, Tuple

from config import get_config
from utils.logger_loguru import get_logger

_log = get_logger("WSReconnectReconcile")

_pending: set[str] = set()
_lock = threading.Lock()
_worker_running = False
_last_reconcile_fingerprint: Dict[int, Tuple[str, float]] = {}


def ws_reconnect_reconcile_enabled() -> bool:
    return bool(get_config("chat.ws_reconnect_reconcile_enabled", True))


def _enqueue_unreplied_enabled() -> bool:
    return bool(get_config("chat.ws_reconnect_enqueue_unreplied", True))


def _reconcile_cooldown_sec() -> int:
    try:
        return int(get_config("chat.ws_reconnect_reconcile_cooldown_sec", 120) or 120)
    except (TypeError, ValueError):
        return 120


def _should_enqueue_reconcile(session_id: int, text: str) -> bool:
    """同一会话相同未回复内容在冷却期内不重复入队（避免频繁重连风暴）。"""
    body = (text or "").strip()
    if not body:
        return False
    fp = hashlib.sha256(body.encode("utf-8")).hexdigest()[:20]
    now = time.time()
    cooldown = max(30, _reconcile_cooldown_sec())
    prev = _last_reconcile_fingerprint.get(int(session_id))
    if prev and prev[0] == fp and now - prev[1] < cooldown:
        return False
    _last_reconcile_fingerprint[int(session_id)] = (fp, now)
    if len(_last_reconcile_fingerprint) > 2000:
        cutoff = now - cooldown
        stale = [k for k, (_, ts) in _last_reconcile_fingerprint.items() if ts < cutoff]
        for k in stale:
            _last_reconcile_fingerprint.pop(k, None)
    return True


def schedule_reconcile_after_auth(
    *,
    channel_name: str,
    shop_id: str,
    user_id: str,
    username: str,
) -> None:
    """每次 WS AUTH 成功后调度后台补偿（首次连接与重连均会触发）。"""
    if not ws_reconnect_reconcile_enabled():
        return
    key = f"{channel_name}:{shop_id}:{user_id}"
    with _lock:
        _pending.add(key)
        global _worker_running
        if _worker_running:
            return
        _worker_running = True

    def _run() -> None:
        global _worker_running
        try:
            while True:
                with _lock:
                    if not _pending:
                        break
                    key = _pending.pop()
                ch, shop, seller = key.split(":", 2)
                try:
                    reconcile_account_after_auth(
                        channel_name=ch,
                        shop_id=shop,
                        user_id=seller,
                        username=username,
                    )
                except Exception as e:
                    _log.debug("WS 重连补偿失败 {}: {}", key, e)
        finally:
            with _lock:
                still = bool(_pending)
                _worker_running = still
            if still:
                schedule_reconcile_after_auth(
                    channel_name=channel_name,
                    shop_id=shop_id,
                    user_id=user_id,
                    username=username,
                )

    threading.Thread(
        target=_run, daemon=True, name="WSReconnectReconcile"
    ).start()


def reconcile_account_after_auth(
    *,
    channel_name: str,
    shop_id: str,
    user_id: str,
    username: str,
) -> int:
    """
    拉 MMS 会话摘要，并将各 active 会话的未回复买家消息重新入队。

    Returns:
        入队会话数。
    """
    from database.db_manager import db_manager

    acc = db_manager.get_account(channel_name, str(shop_id), str(user_id))
    if not acc or not acc.get("id"):
        return 0
    account_id = int(acc["id"])

    try:
        from core.mms_session_sync import mms_session_sync_enabled, sync_mms_sessions_for_account

        if mms_session_sync_enabled():
            sync_mms_sessions_for_account(account_id, reconnect_boost=True)
    except Exception as e:
        _log.debug("WS 补偿 MMS 同步跳过: {}", e)

    if not _enqueue_unreplied_enabled():
        return 0

    from Channel.pinduoduo.ws_config import queue_name_for_account
    from utils.transfer_takeover import _build_synthetic_context
    from utils.unreplied_buyer_messages import (
        get_unreplied_buyer_messages,
        merge_unreplied_parts,
    )

    queue_name = queue_name_for_account(str(shop_id), str(user_id))
    max_parts = int(get_config("chat.unreplied_buyer_max_parts", 3) or 3)
    enqueued = 0

    for sess in db_manager.get_chat_sessions(account_id, "active"):
        sid = int(sess.get("id") or 0)
        buyer_uid = str(sess.get("buyer_uid") or "").strip()
        if not sid or not buyer_uid:
            continue
        parts = get_unreplied_buyer_messages(sid, max_count=max_parts)
        if not parts:
            continue
        text = merge_unreplied_parts(parts)
        if not text.strip():
            continue
        if not _should_enqueue_reconcile(sid, text):
            continue
        ctx = _build_synthetic_context(
            text=text,
            buyer_uid=buyer_uid,
            shop_id=str(shop_id),
            seller_user_id=str(user_id),
            username=str(username or acc.get("username") or ""),
            channel_name=channel_name,
        )
        raw = getattr(ctx.kwargs, "raw_data", None) or {}
        if isinstance(raw, dict):
            raw["_ws_reconnect_reconcile"] = True
            ctx.kwargs.raw_data = raw
        try:
            _enqueue_context(queue_name, ctx, account_id=account_id)
            enqueued += 1
        except Exception as e:
            _log.debug(
                "WS 补偿入队失败 buyer={} session={}: {}",
                buyer_uid,
                sid,
                e,
            )

    if enqueued:
        _log.info(
            "WS 认证后补偿入队: shop={} user={} sessions={}",
            shop_id,
            user_id,
            enqueued,
        )
    return enqueued


def _enqueue_context(
    queue_name: str, context: Any, *, account_id: Optional[int] = None
) -> None:
    import asyncio

    async def _put() -> None:
        from Message import put_message

        await put_message(queue_name, context)

    try:
        from ui.auto_reply_ui import auto_reply_manager

        target_loop = None
        for thread in auto_reply_manager.running_accounts.values():
            acc = getattr(thread, "account_data", None) or {}
            if account_id is not None and int(acc.get("id") or 0) == int(account_id):
                target_loop = getattr(thread, "loop", None)
                break
            ku = getattr(context, "kwargs", None)
            ctx_shop = str(getattr(ku, "shop_id", "") or "")
            ctx_user = str(getattr(ku, "user_id", "") or "")
            if (
                str(acc.get("shop_id") or "") == ctx_shop
                and str(acc.get("user_id") or "") == ctx_user
            ):
                target_loop = getattr(thread, "loop", None)
                break
        if target_loop is not None and target_loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(_put(), target_loop)
            fut.result(timeout=30)
            return
    except Exception as e:
        _log.debug("WS 补偿入队走账号 loop 失败: {}", e)
    asyncio.run(_put())
