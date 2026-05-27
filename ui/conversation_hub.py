"""
会话列表与聊天记录（供自动回复界面按账号分组展示、人工回复）。
在 WebSocket 收到可关联买家的消息时写入；发送成功时追加客服侧记录。
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

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
    nickname: str = "买家"
    preview: str = ""
    updated_at: float = 0.0
    messages: Deque[Tuple[str, str, float]] = field(
        default_factory=lambda: deque(maxlen=300)
    )


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

        ct, _row_body, _img = split_chat_body_for_storage(context, raw_preview)
        if ct == "image":
            preview = "[图片]"
        elif ct == "video":
            preview = "[视频]"
        else:
            preview = raw_preview

        is_mall_cs = context.type == ContextType.MALL_CS
        role = "agent" if is_mall_cs else "user"
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
                persist_seller_mall_cs_from_context,
            )

            if is_mall_cs:
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
                st.nickname = nickname or st.nickname
            st.preview = preview or st.preview
            st.updated_at = time.time()
            st.messages.append((role, preview, ts))

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
            st.preview = _preview_text(text)
            st.updated_at = ts
            st.messages.append(("agent", text, ts))
        self._emit_hub_updates(account_key, customer_uid, "agent", text, ts)

    def get_conversation_rows(self, account_key: str) -> List[Dict[str, Any]]:
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
                    }
                )
            rows.sort(key=lambda r: r["updated_at"], reverse=True)
            return rows

    def get_messages(self, account_key: str, customer_uid: str) -> List[Tuple[str, str, float]]:
        with self._lock:
            acc = self._by_account.get(account_key, {})
            st = acc.get(customer_uid)
            if not st:
                return []
            return list(st.messages)

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
