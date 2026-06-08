"""chat_messages 批量写入缓冲，降低 SQLite 提交频率。"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional

from utils.logger_loguru import get_logger

_log = get_logger("ChatMessageBuffer")

FLUSH_INTERVAL_SEC = 0.5
FLUSH_BATCH_SIZE = 10
_MAX_PENDING = 5000


@dataclass
class _PendingChatMessage:
    session_id: int
    account_id: int
    sender_type: str
    content: str
    message_id: Optional[str] = None
    content_type: str = "text"
    image_url: Optional[str] = None
    increment_unread: bool = False
    sent_at: Optional[datetime] = None


_buffer_instance: Optional["ChatMessageWriteBuffer"] = None
_buffer_lock = threading.Lock()


def _buffer_enabled() -> bool:
    if os.environ.get("CHAT_MESSAGE_BUFFER_DISABLE", "").strip() in ("1", "true", "yes"):
        return False
    try:
        from config import get_config

        return bool(get_config("chat.message_write_batch_enabled", True))
    except Exception:
        return True


class ChatMessageWriteBuffer:
    """每 0.5 秒或累计 10 条消息时批量落库。"""

    def __init__(self) -> None:
        self._pending: List[_PendingChatMessage] = []
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._db = None

    def _get_db(self):
        if self._db is None:
            from database.db_manager import db_manager

            self._db = db_manager
        return self._db

    def enqueue(
        self,
        *,
        session_id: int,
        account_id: int,
        sender_type: str,
        content: str,
        message_id: Optional[str] = None,
        content_type: str = "text",
        image_url: Optional[str] = None,
        increment_unread: bool = False,
        sent_at: Optional[datetime] = None,
    ) -> None:
        item = _PendingChatMessage(
            session_id=session_id,
            account_id=account_id,
            sender_type=sender_type,
            content=content,
            message_id=message_id,
            content_type=content_type,
            image_url=image_url,
            increment_unread=increment_unread,
            sent_at=sent_at,
        )
        with self._lock:
            self._pending.append(item)
            if len(self._pending) >= FLUSH_BATCH_SIZE:
                self._flush_locked()
                return
            if self._timer is None:
                self._timer = threading.Timer(FLUSH_INTERVAL_SEC, self._flush_async)
                self._timer.daemon = True
                self._timer.name = "chat-msg-buffer-flush"
                self._timer.start()

    def _flush_async(self) -> None:
        try:
            self.flush()
        except Exception as exc:
            _log.error("异步刷新 chat_messages 失败: {}", exc)

    def flush(self) -> int:
        with self._lock:
            return self._flush_locked()

    def _requeue_failed_batch(self, batch: List[_PendingChatMessage]) -> None:
        if not batch:
            return
        self._pending = batch + self._pending
        overflow = len(self._pending) - _MAX_PENDING
        if overflow > 0:
            self._pending = self._pending[:_MAX_PENDING]
            _log.error(
                "chat_messages 缓冲溢出，丢弃最旧 {} 条（当前上限 {}）",
                overflow,
                _MAX_PENDING,
            )

    def _flush_locked(self) -> int:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if not self._pending:
            return 0
        batch = self._pending
        self._pending = []
        try:
            return self._get_db().add_chat_messages_batch(batch)
        except Exception as exc:
            _log.error("批量写入 chat_messages 失败 ({} 条): {}", len(batch), exc)
            self._requeue_failed_batch(batch)
            return 0


def get_chat_message_buffer() -> ChatMessageWriteBuffer:
    global _buffer_instance
    with _buffer_lock:
        if _buffer_instance is None:
            _buffer_instance = ChatMessageWriteBuffer()
        return _buffer_instance


def flush_chat_message_buffer() -> int:
    if not _buffer_enabled():
        return 0
    return get_chat_message_buffer().flush()
