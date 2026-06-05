"""
会话列表与聊天记录（供自动回复界面按账号分组展示、人工回复）。
在 WebSocket 收到可关联买家的消息时写入；发送成功时追加客服侧记录。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

from bridge.context import Context, ContextType

from utils.logger_loguru import get_logger

_hub_log = get_logger("ConversationHub")


def make_account_key(channel_name: str, shop_id: str, username: str) -> str:
    return f"{channel_name}_{shop_id}_{username}"


def _preview_text(content: Any, max_len: int = 80) -> str:
    if content is None:
        return ""
    if isinstance(content, dict):
        import json

        s = json.dumps(content, ensure_ascii=False)
    else:
        s = str(content)
    s = s.replace("\n", " ").strip()
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def parse_peer_from_context(context: Context) -> Tuple[Optional[str], str]:
    """解析买家 uid 与展示名。"""
    if context.type == ContextType.TRANSFER:
        from utils.pdd_transfer import resolve_buyer_uid_from_transfer

        buid = resolve_buyer_uid_from_transfer(context)
        if buid:
            nick = (getattr(context.kwargs, "nickname", None) or "").strip() or "买家"
            return buid, nick
    ku = context.kwargs
    from_user = (ku.from_user or "").lower()
    to_user = (ku.to_user or "").lower()
    name = (ku.nickname or "").strip() or "买家"
    if from_user == "user" and ku.from_uid:
        return str(ku.from_uid), name
    if to_user == "user" and ku.to_uid:
        return str(ku.to_uid), name
    # 手机 / 其他端以 mall_cs 发给买家：from=mall_cs, to=user
    if from_user == "mall_cs" and to_user == "user" and ku.to_uid:
        return str(ku.to_uid), name
    return None, name


_SKIP_TYPES = frozenset(
    {
        ContextType.AUTH,
        ContextType.SYSTEM_STATUS,
        ContextType.MALL_SYSTEM_MSG,
    }
)


@dataclass
class _ConvState:
    """会话摘要（不含完整消息列表）。"""

    nickname: str = "买家"
    preview: str = ""
    updated_at: float = 0.0
    unread_count: int = 0
    session_id: Optional[int] = None


class ConversationHub(QObject):
    """
    线程安全的会话索引 + Qt 信号（可从 WebSocket 线程 emit，槽在主线程执行）。
    """

    list_changed = pyqtSignal(str)
    message_logged = pyqtSignal(str, str, str, str, float)
    total_unread_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._by_account: Dict[str, Dict[str, _ConvState]] = {}
        self._account_id_by_key: Dict[str, int] = {}

    def sync_latest_conversations(
        self, account_key: str, account_id: int
    ) -> List[Dict[str, Any]]:
        """从 chat_sessions 同步摘要到内存，不加载完整消息。"""
        from database.db_manager import db_manager

        rows = db_manager.get_chat_session_summaries(account_id, "active")
        with self._lock:
            self._account_id_by_key[account_key] = int(account_id)
            acc = self._by_account.setdefault(account_key, {})
            synced_uids = set()
            for s in rows:
                uid = str(s.get("buyer_uid") or "")
                if not uid:
                    continue
                synced_uids.add(uid)
                st = acc.get(uid)
                if st is None:
                    st = _ConvState()
                    acc[uid] = st
                st.nickname = s.get("buyer_nickname") or st.nickname or "买家"
                st.preview = s.get("last_message") or st.preview
                st.unread_count = int(s.get("unread_count") or 0)
                st.session_id = int(s["id"]) if s.get("id") is not None else None
                t = s.get("last_message_time") or s.get("updated_at")
                if t is not None:
                    try:
                        st.updated_at = float(t.timestamp())
                    except AttributeError:
                        st.updated_at = float(t) if t else st.updated_at
            for uid in list(acc.keys()):
                if uid not in synced_uids:
                    del acc[uid]
        return rows

    def _touch_summary(
        self,
        st: _ConvState,
        *,
        nickname: str,
        preview: str,
        ts: float,
        role: str,
        session_id: Optional[int] = None,
    ) -> None:
        if nickname:
            st.nickname = nickname
        if preview:
            st.preview = preview[:50] + ("…" if len(preview) > 50 else "")
        st.updated_at = ts
        if session_id is not None:
            st.session_id = session_id
        if role == "user":
            st.unread_count = int(st.unread_count or 0) + 1
        elif role in ("agent", "system"):
            pass

    def record_from_context(
        self,
        channel_name: str,
        shop_id: str,
        user_id: str,
        username: str,
        context: Context,
    ) -> None:
        if context.type in _SKIP_TYPES:
            return
        peer_uid, nickname = parse_peer_from_context(context)
        if not peer_uid:
            return
        account_key = make_account_key(channel_name, shop_id, username)
        raw_preview = _preview_text(context.content)
        ts = time.time()
        if context.kwargs.timestamp is not None:
            try:
                ts = float(context.kwargs.timestamp) / 1000.0
            except (TypeError, ValueError):
                _hub_log.debug("解析消息时间戳失败，使用当前时间")
        from database.chat_persist import split_chat_body_for_storage

        is_mall_cs = context.type == ContextType.MALL_CS
        is_transfer = context.type == ContextType.TRANSFER
        if is_transfer:
            from utils.pdd_transfer import format_transfer_system_preview

            preview = format_transfer_system_preview(context)
        else:
            ct, _row_body, _img = split_chat_body_for_storage(context, raw_preview)
            if ct == "image":
                preview = "[图片]"
            elif ct == "video":
                preview = "[视频]"
            else:
                preview = raw_preview
        role = "system" if is_transfer else ("agent" if is_mall_cs else "user")
        mid = getattr(context.kwargs, "msg_id", None)
        if mid is not None:
            mid = str(mid) if mid else None

        buyer_nick_for_db = nickname or "买家"
        if is_mall_cs:
            with self._lock:
                st0 = self._by_account.get(account_key, {}).get(peer_uid)
                if st0 is not None and (st0.nickname or "").strip():
                    buyer_nick_for_db = st0.nickname

        try:
            from database.chat_persist import (
                persist_customer_from_context,
                persist_inbound_transfer_from_context,
                persist_seller_mall_cs_from_context,
            )

            if is_transfer:
                persist_inbound_transfer_from_context(
                    channel_name,
                    shop_id,
                    user_id,
                    username,
                    peer_uid,
                    nickname or "买家",
                    preview,
                    mid,
                    ts,
                )
            elif is_mall_cs:
                persist_seller_mall_cs_from_context(
                    channel_name,
                    shop_id,
                    user_id,
                    username,
                    peer_uid,
                    buyer_nick_for_db,
                    context,
                    raw_preview,
                    mid,
                    ts,
                )
            else:
                persist_customer_from_context(
                    channel_name,
                    shop_id,
                    user_id,
                    username,
                    peer_uid,
                    nickname or "买家",
                    raw_preview,
                    mid,
                    ts,
                    context=context,
                )
        except Exception as e:
            _hub_log.warning("persist from context 失败: {}", e)

        with self._lock:
            acc = self._by_account.setdefault(account_key, {})
            st = acc.get(peer_uid)
            if is_mall_cs:
                if st is None:
                    st = _ConvState(nickname="买家")
                    acc[peer_uid] = st
            else:
                if st is None:
                    st = _ConvState(nickname=nickname or "买家")
                    acc[peer_uid] = st
            self._touch_summary(
                st,
                nickname=nickname or st.nickname,
                preview=preview,
                ts=time.time(),
                role=role,
            )

        self._emit_hub_updates(account_key, peer_uid, role, preview, ts)

    def _emit_hub_updates(
        self,
        account_key: str,
        peer_uid: str,
        role: str,
        preview: str,
        ts: float,
    ) -> None:
        def _do() -> None:
            self.list_changed.emit(account_key)
            self.message_logged.emit(account_key, peer_uid, role, preview, ts)
            try:
                from database.db_manager import db_manager

                self.total_unread_changed.emit(db_manager.get_total_unread_chat())
            except Exception as e:
                _hub_log.warning("刷新未读总数失败: {}", e)

        from utils.qt_threading import run_on_main_thread

        run_on_main_thread(_do)

    def record_platform_civility_from_context(
        self,
        channel_name: str,
        shop_id: str,
        user_id: str,
        username: str,
        context: Context,
    ) -> None:
        """平台文明用语提示：写入 system 侧记录，不计为商家已回复。"""
        peer_uid, nickname = parse_peer_from_context(context)
        if not peer_uid:
            return
        account_key = make_account_key(channel_name, shop_id, username)
        raw_preview = _preview_text(context.content)
        ts = time.time()
        if context.kwargs.timestamp is not None:
            try:
                ts = float(context.kwargs.timestamp) / 1000.0
            except (TypeError, ValueError):
                _hub_log.debug("解析消息时间戳失败，使用当前时间")
        try:
            from database.chat_persist import persist_platform_civility_from_context

            persist_platform_civility_from_context(
                channel_name,
                shop_id,
                user_id,
                username,
                peer_uid,
                nickname or "买家",
                raw_preview,
                getattr(context.kwargs, "msg_id", None),
                ts,
            )
        except Exception as e:
            _hub_log.warning("persist platform civility 失败: {}", e)
        with self._lock:
            acc = self._by_account.setdefault(account_key, {})
            st = acc.get(peer_uid)
            if st is None:
                st = _ConvState(nickname=nickname or "买家")
                acc[peer_uid] = st
            st.preview = raw_preview or st.preview
            self._touch_summary(
                st,
                nickname=nickname or st.nickname,
                preview=raw_preview,
                ts=time.time(),
                role="system",
            )
        self._emit_hub_updates(account_key, peer_uid, "system", raw_preview, ts)

    def record_manual_sent(
        self,
        channel_name: str,
        shop_id: str,
        username: str,
        customer_uid: str,
        text: str,
        seller_user_id: str,
    ) -> None:
        account_key = make_account_key(channel_name, shop_id, username)
        ts = time.time()
        try:
            from database.chat_persist import persist_human_message

            persist_human_message(
                channel_name,
                shop_id,
                seller_user_id,
                username,
                customer_uid,
                text,
            )
        except Exception as e:
            _hub_log.warning("persist_human_message 失败: {}", e)
        with self._lock:
            acc = self._by_account.setdefault(account_key, {})
            st = acc.get(customer_uid)
            if st is None:
                st = _ConvState(nickname="买家")
                acc[customer_uid] = st
            st.preview = _preview_text(text, max_len=50)
            self._touch_summary(
                st,
                nickname=st.nickname,
                preview=text,
                ts=ts,
                role="agent",
            )
        self._emit_hub_updates(account_key, customer_uid, "agent", text, ts)

    def get_conversation_rows(self, account_key: str) -> List[Dict[str, Any]]:
        account_id = self._account_id_by_key.get(account_key)
        if account_id is not None:
            rows = self.sync_latest_conversations(account_key, account_id)
            return [
                {
                    "customer_uid": str(s.get("buyer_uid") or ""),
                    "nickname": s.get("buyer_nickname") or "买家",
                    "preview": s.get("last_message") or "",
                    "updated_at": (
                        float(s["last_message_time"].timestamp())
                        if s.get("last_message_time") is not None
                        else float(s["updated_at"].timestamp())
                        if s.get("updated_at") is not None
                        else 0.0
                    ),
                    "unread_count": int(s.get("unread_count") or 0),
                    "session_id": s.get("id"),
                }
                for s in rows
            ]
        with self._lock:
            acc = self._by_account.get(account_key, {})
            rows = []
            for uid, st in acc.items():
                rows.append(
                    {
                        "customer_uid": uid,
                        "nickname": st.nickname,
                        "preview": st.preview,
                        "updated_at": st.updated_at,
                        "unread_count": st.unread_count,
                        "session_id": st.session_id,
                    }
                )
            rows.sort(key=lambda r: r["updated_at"], reverse=True)
            return rows

    def get_messages(self, account_key: str, customer_uid: str) -> List[Tuple[str, str, float]]:
        """兼容旧接口：不再缓存完整消息，请从数据库分页加载。"""
        return []

    def clear_conversation(self, account_key: str, customer_uid: str) -> None:
        with self._lock:
            acc = self._by_account.get(account_key)
            if not acc:
                return
            if customer_uid in acc:
                del acc[customer_uid]
        from utils.qt_threading import run_on_main_thread

        run_on_main_thread(lambda: self.list_changed.emit(account_key))


_conversation_hub: Optional[ConversationHub] = None


def get_conversation_hub() -> ConversationHub:
    global _conversation_hub
    if _conversation_hub is None:
        _conversation_hub = ConversationHub()
    return _conversation_hub
