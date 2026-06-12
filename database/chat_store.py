# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""聊天会话 / 消息 / 快捷回复 — 从 DatabaseManager 拆出。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc, func, or_, tuple_
from sqlalchemy.exc import SQLAlchemyError

from database.models import (
    Account,
    Channel,
    ChatMessage,
    ChatSession,
    QuickReply,
    Shop,
)
from utils.chat_time import now_for_db, shanghai_naive_now


class ChatStoreMixin:
    """DatabaseManager 的聊天相关数据访问。"""

    def list_all_accounts_for_chat(self) -> List[Dict[str, Any]]:
        """所有接待账号（含店铺、渠道），供实时聊天侧栏使用。"""
        session = self.get_session()
        try:
            rows = (
                session.query(Account, Shop, Channel)
                .join(Shop, Account.shop_id == Shop.id)
                .join(Channel, Shop.channel_id == Channel.id)
                .all()
            )
            out: List[Dict[str, Any]] = []
            for acc, shop, ch in rows:
                out.append(
                    {
                        "id": acc.id,
                        "channel_name": ch.channel_name,
                        "platform_shop_id": shop.shop_id,
                        "shop_name": shop.shop_name,
                        "shop_logo": shop.shop_logo,
                        "seller_user_id": acc.user_id,
                        "username": acc.username,
                        "status": acc.status,
                    }
                )
            return out
        except SQLAlchemyError as e:
            self.logger.error(f"list_all_accounts_for_chat 失败: {e}")
            return []
        finally:
            session.close()

    def get_account_row_by_id(self, account_id: int) -> Optional[Dict[str, Any]]:
        session = self.get_session()
        try:
            row = (
                session.query(Account, Shop, Channel)
                .join(Shop, Account.shop_id == Shop.id)
                .join(Channel, Shop.channel_id == Channel.id)
                .filter(Account.id == account_id)
                .first()
            )
            if not row:
                return None
            acc, shop, ch = row
            from utils.credential_crypto import maybe_decrypt_from_storage

            return {
                "id": acc.id,
                "channel_name": ch.channel_name,
                "platform_shop_id": shop.shop_id,
                "shop_name": shop.shop_name,
                "shop_logo": shop.shop_logo,
                "seller_user_id": acc.user_id,
                "username": acc.username,
                "status": acc.status,
                "cookies": maybe_decrypt_from_storage(acc.cookies),
            }
        finally:
            session.close()

    @staticmethod
    def _truncate_session_preview(text: Optional[str], max_len: int = 50) -> str:
        s = (text or "").replace("\n", " ").strip()
        if len(s) <= max_len:
            return s
        return s[: max_len - 1] + "…"

    def _count_unread_buyer_messages_bulk(
        self, session_ids: List[int]
    ) -> Dict[int, int]:
        if not session_ids:
            return {}
        db = self.get_session()
        try:
            rows = (
                db.query(ChatMessage.session_id, func.count(ChatMessage.id))
                .filter(
                    ChatMessage.session_id.in_(session_ids),
                    ChatMessage.is_read == False,  # noqa: E712
                    ChatMessage.sender_type == "customer",
                )
                .group_by(ChatMessage.session_id)
                .all()
            )
            return {int(sid): int(cnt) for sid, cnt in rows}
        except SQLAlchemyError as e:
            self.logger.error(f"_count_unread_buyer_messages_bulk 失败: {e}")
            return {}
        finally:
            db.close()

    def count_unread_buyer_messages(self, session_id: int) -> int:
        """实时统计买家未读消息数。"""
        return self._count_unread_buyer_messages_bulk([session_id]).get(session_id, 0)

    def get_unread_sum_by_account(self) -> Dict[int, int]:
        """按接待账号汇总买家未读数（单条 SQL，供左侧账号列表使用）。"""
        db = self.get_session()
        try:
            rows = (
                db.query(ChatSession.account_id, func.count(ChatMessage.id))
                .join(ChatMessage, ChatMessage.session_id == ChatSession.id)
                .filter(
                    ChatMessage.is_read == False,  # noqa: E712
                    ChatMessage.sender_type == "customer",
                )
                .group_by(ChatSession.account_id)
                .all()
            )
            return {
                int(aid): int(cnt)
                for aid, cnt in rows
                if aid is not None
            }
        except SQLAlchemyError as e:
            self.logger.error(f"get_unread_sum_by_account 失败: {e}")
            return {}
        finally:
            db.close()

    def get_chat_session_summaries(
        self, account_id: Optional[int] = None, status: Optional[str] = "active"
    ) -> List[Dict[str, Any]]:
        """会话列表摘要：不含完整消息，未读数实时计算。status=None 表示不限状态。"""
        session = self.get_session()
        try:
            q = session.query(ChatSession)
            if status is not None:
                q = q.filter(ChatSession.status == status)
            if account_id is not None:
                q = q.filter(ChatSession.account_id == account_id)
            q = q.order_by(desc(ChatSession.updated_at))
            rows = q.all()
            unread_map = self._count_unread_buyer_messages_bulk([s.id for s in rows])
            return [
                {
                    "id": s.id,
                    "account_id": s.account_id,
                    "account_name": s.account_name,
                    "platform_shop_id": s.platform_shop_id,
                    "buyer_uid": s.buyer_uid,
                    "buyer_nickname": s.buyer_nickname,
                    "avatar_url": s.avatar_url,
                    "status": s.status,
                    "ai_mode": bool(s.ai_mode),
                    "last_message": self._truncate_session_preview(s.last_message),
                    "last_message_time": s.last_message_time,
                    "unread_count": unread_map.get(s.id, 0),
                    "updated_at": s.updated_at,
                }
                for s in rows
            ]
        except SQLAlchemyError as e:
            self.logger.error(f"get_chat_session_summaries 失败: {e}")
            return []
        finally:
            session.close()

    def get_chat_sessions(
        self, account_id: Optional[int] = None, status: Optional[str] = "active"
    ) -> List[Dict[str, Any]]:
        return self.get_chat_session_summaries(account_id, status)

    def reopen_chat_session(self, session_id: int) -> bool:
        """将 closed 会话重新标为 active（人工再次打开时）。"""
        session = self.get_session()
        try:
            s = session.query(ChatSession).filter(ChatSession.id == int(session_id)).first()
            if not s or (s.status or "active") != "closed":
                return False
            s.status = "active"
            s.updated_at = now_for_db()
            session.commit()
            try:
                from Agent.CustomerAgent.conversation_memory import (
                    reset_session_flow_memory,
                )

                reset_session_flow_memory(int(s.id), source="SessionReopenManual")
            except Exception as e:
                self.logger.debug(
                    "reopen_chat_session 重置 task_state 失败 session={}: {}",
                    s.id,
                    e,
                )
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"reopen_chat_session 失败: {e}")
            return False
        finally:
            session.close()

    def get_chat_session_by_buyer(
        self, account_id: int, buyer_uid: str, status: str = "active"
    ) -> Optional[Dict[str, Any]]:
        session = self.get_session()
        try:
            q = session.query(ChatSession).filter(
                ChatSession.account_id == int(account_id),
                ChatSession.buyer_uid == str(buyer_uid),
            )
            if status:
                q = q.filter(ChatSession.status == str(status))
            s = q.first()
            if s is None:
                return None
            unread = self._count_unread_buyer_messages_bulk([s.id]).get(s.id, 0)
            return {
                "id": s.id,
                "account_id": s.account_id,
                "account_name": s.account_name,
                "platform_shop_id": s.platform_shop_id,
                "buyer_uid": s.buyer_uid,
                "buyer_nickname": s.buyer_nickname,
                "avatar_url": s.avatar_url,
                "status": s.status,
                "ai_mode": bool(s.ai_mode),
                "last_message": self._truncate_session_preview(s.last_message),
                "last_message_time": s.last_message_time,
                "unread_count": unread,
                "updated_at": s.updated_at,
            }
        except SQLAlchemyError as e:
            self.logger.error(f"get_chat_session_by_buyer 失败: {e}")
            return None
        finally:
            session.close()

    def find_chat_session_by_buyer_any_status(
        self, account_id: int, buyer_uid: str
    ) -> Optional[Dict[str, Any]]:
        """按买家 UID 查会话（不限 status），未读数实时计算。"""
        session = self.get_session()
        try:
            s = (
                session.query(ChatSession)
                .filter(
                    ChatSession.account_id == int(account_id),
                    ChatSession.buyer_uid == str(buyer_uid),
                )
                .order_by(desc(ChatSession.updated_at))
                .first()
            )
            if not s:
                return None
            unread = self.count_unread_buyer_messages(s.id)
            return {
                "id": s.id,
                "account_id": s.account_id,
                "account_name": s.account_name,
                "platform_shop_id": s.platform_shop_id,
                "buyer_uid": s.buyer_uid,
                "buyer_nickname": s.buyer_nickname,
                "avatar_url": s.avatar_url,
                "status": s.status,
                "ai_mode": bool(s.ai_mode),
                "last_message": self._truncate_session_preview(s.last_message),
                "last_message_time": s.last_message_time,
                "unread_count": unread,
                "updated_at": s.updated_at,
            }
        except SQLAlchemyError as e:
            self.logger.error(f"find_chat_session_by_buyer_any_status 失败: {e}")
            return None
        finally:
            session.close()

    def get_chat_session_by_id(self, session_id: int) -> Optional[Dict[str, Any]]:
        """按主键读取会话，避免界面树节点上缓存的 ai_mode 等字段过期。"""
        session = self.get_session()
        try:
            s = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not s:
                return None
            unread = self.count_unread_buyer_messages(s.id)
            return {
                "id": s.id,
                "account_id": s.account_id,
                "account_name": s.account_name,
                "platform_shop_id": s.platform_shop_id,
                "buyer_uid": s.buyer_uid,
                "buyer_nickname": s.buyer_nickname,
                "avatar_url": s.avatar_url,
                "status": s.status,
                "ai_mode": bool(s.ai_mode),
                "last_message": self._truncate_session_preview(s.last_message),
                "last_message_time": s.last_message_time,
                "unread_count": unread,
                "updated_at": s.updated_at,
            }
        except SQLAlchemyError as e:
            self.logger.error(f"get_chat_session_by_id 失败: {e}")
            return None
        finally:
            session.close()

    def get_or_create_chat_session(
        self,
        account_id: int,
        platform_shop_id: str,
        account_name: str,
        buyer_uid: str,
        buyer_nickname: str,
        avatar_url: Optional[str] = None,
    ) -> int:
        session = self.get_session()
        try:
            s = (
                session.query(ChatSession)
                .filter(
                    ChatSession.account_id == account_id,
                    ChatSession.buyer_uid == buyer_uid,
                )
                .first()
            )
            now = now_for_db()
            if s:
                s.buyer_nickname = buyer_nickname or s.buyer_nickname
                if avatar_url:
                    s.avatar_url = avatar_url
                reopening = s.status == "closed"
                if reopening:
                    s.status = "active"
                s.updated_at = now
                session.commit()
                if reopening:
                    try:
                        from Agent.CustomerAgent.conversation_memory import (
                            reset_session_flow_memory,
                        )

                        reset_session_flow_memory(
                            int(s.id), source="SessionReopen"
                        )
                    except Exception as e:
                        self.logger.debug(
                            "重开会话重置 task_state 失败 session={}: {}",
                            s.id,
                            e,
                        )
                return s.id
            s = ChatSession(
                account_id=account_id,
                account_name=account_name,
                platform_shop_id=platform_shop_id,
                buyer_uid=buyer_uid,
                buyer_nickname=buyer_nickname or "买家",
                avatar_url=avatar_url,
                status="active",
                ai_mode=self._default_ai_mode_for_account(account_id),
                unread_count=0,
                created_at=now,
                updated_at=now,
            )
            session.add(s)
            session.commit()
            session.refresh(s)
            return s.id
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"get_or_create_chat_session 失败: {e}")
            raise
        finally:
            session.close()

    def update_session_last_message(
        self, session_id: int, message: str, t: Optional[datetime] = None
    ) -> bool:
        session = self.get_session()
        try:
            s = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not s:
                return False
            s.last_message = message
            s.last_message_time = t or now_for_db()
            s.updated_at = now_for_db()
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"update_session_last_message 失败: {e}")
            return False
        finally:
            session.close()

    def close_chat_session(self, session_id: int) -> bool:
        session = self.get_session()
        try:
            s = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not s:
                return False
            s.status = "closed"
            s.updated_at = now_for_db()
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"close_chat_session 失败: {e}")
            return False
        finally:
            session.close()

    def close_idle_chat_sessions(self, idle_seconds: int = 300) -> List[Tuple[int, str, str]]:
        """
        买家最后一条消息超过 idle_seconds 的 active 会话标为 closed（已解决）。

        跳过：当前在「实时聊天」中打开的会话；从未收到买家消息的会话。

        Returns:
            [(account_id, buyer_uid, account_key), ...]
        """
        from datetime import timedelta

        from database.chat_persist import is_active_chat
        from utils.chat_time import shanghai_naive_now

        now = shanghai_naive_now()
        cutoff = now - timedelta(seconds=int(idle_seconds))
        closed: List[Tuple[int, str, str]] = []
        session = self.get_session()
        try:
            rows = (
                session.query(ChatSession)
                .filter(ChatSession.status == "active")
                .all()
            )
            for cs in rows:
                if is_active_chat(int(cs.account_id), str(cs.buyer_uid)):
                    continue
                last_customer = (
                    session.query(func.max(ChatMessage.sent_at))
                    .filter(
                        ChatMessage.session_id == cs.id,
                        ChatMessage.sender_type == "customer",
                    )
                    .scalar()
                )
                if last_customer is None:
                    continue
                if last_customer > cutoff:
                    continue
                cs.status = "closed"
                cs.updated_at = now_for_db()
                try:
                    from Agent.CustomerAgent.conversation_memory import (
                        reset_session_flow_memory,
                    )

                    reset_session_flow_memory(
                        int(cs.id), source="SessionIdleClose"
                    )
                except Exception as e:
                    self.logger.debug(
                        "结案重置 task_state 失败 session={}: {}", cs.id, e
                    )
                acc = (
                    session.query(Account, Shop, Channel)
                    .join(Shop, Account.shop_id == Shop.id)
                    .join(Channel, Shop.channel_id == Channel.id)
                    .filter(Account.id == cs.account_id)
                    .first()
                )
                account_key = ""
                if acc:
                    _acc, _shop, _ch = acc
                    account_key = (
                        f"{_ch.channel_name}:{_shop.shop_id}:{_acc.username}"
                    )
                closed.append((int(cs.account_id), str(cs.buyer_uid), account_key))
            if closed:
                session.commit()
            return closed
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"close_idle_chat_sessions 失败: {e}")
            return []
        finally:
            session.close()

    def set_session_ai_mode(self, session_id: int, ai_mode: bool) -> bool:
        session = self.get_session()
        try:
            s = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not s:
                return False
            s.ai_mode = ai_mode
            s.updated_at = now_for_db()
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"set_session_ai_mode 失败: {e}")
            return False
        finally:
            session.close()

    def lock_session_human_atomic(self, session_id: int) -> bool:
        """单事务：ai_mode=False + stage 置 idle 并清空业务槽位。"""
        import json

        session = self.get_session()
        try:
            s = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not s:
                return False
            s.ai_mode = False
            try:
                from Agent.CustomerAgent.conversation_memory import TaskState

                task = TaskState.from_dict(
                    json.loads(s.task_state_json) if s.task_state_json else None
                )
                task.stage = "idle"
                task.flow_node = "idle"
                task.slots = {}
                task.pending_confirm = []
                s.task_state_json = json.dumps(task.to_dict(), ensure_ascii=False)
            except Exception as e:
                self.logger.debug(
                    "lock_session_human_atomic task_state 重置跳过 session={}: {}",
                    session_id,
                    e,
                )
            s.updated_at = now_for_db()
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"lock_session_human_atomic 失败: {e}")
            return False
        finally:
            session.close()

    @staticmethod
    def _default_ai_mode_for_account(account_id: int) -> bool:
        try:
            from utils.weak_supervision import default_ai_mode_for_account

            return default_ai_mode_for_account(int(account_id))
        except Exception:
            return True

    def mark_chat_session_inbound_transferred(self, session_id: int) -> bool:
        session = self.get_session()
        try:
            s = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not s:
                return False
            if s.inbound_transferred_at is not None:
                return True
            s.inbound_transferred_at = now_for_db()
            s.updated_at = now_for_db()
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"mark_chat_session_inbound_transferred 失败: {e}")
            return False
        finally:
            session.close()

    def is_chat_session_inbound_transferred(self, session_id: int) -> bool:
        session = self.get_session()
        try:
            s = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            return bool(s and s.inbound_transferred_at is not None)
        except SQLAlchemyError as e:
            self.logger.error(f"is_chat_session_inbound_transferred 失败: {e}")
            return False
        finally:
            session.close()

    def get_session_memory(self, session_id: int) -> Dict[str, Any]:
        """读取会话三层记忆持久化字段。"""
        session = self.get_session()
        try:
            s = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not s:
                return {}
            return {
                "task_state_json": s.task_state_json,
                "long_term_summary": s.long_term_summary,
                "memory_summary_through_id": int(s.memory_summary_through_id or 0),
            }
        except SQLAlchemyError as e:
            self.logger.error(f"get_session_memory 失败: {e}")
            return {}
        finally:
            session.close()

    def update_session_memory(
        self,
        session_id: int,
        *,
        task_state_json: Optional[str] = None,
        long_term_summary: Optional[str] = None,
        memory_summary_through_id: Optional[int] = None,
    ) -> bool:
        import time

        from sqlalchemy.exc import OperationalError

        last_err: Optional[Exception] = None
        for attempt in range(4):
            session = self.get_session()
            try:
                s = session.query(ChatSession).filter(ChatSession.id == session_id).first()
                if not s:
                    return False
                if task_state_json is not None:
                    s.task_state_json = task_state_json
                if long_term_summary is not None:
                    s.long_term_summary = long_term_summary
                if memory_summary_through_id is not None:
                    s.memory_summary_through_id = memory_summary_through_id
                s.updated_at = now_for_db()
                session.commit()
                return True
            except OperationalError as e:
                session.rollback()
                last_err = e
                if "locked" not in str(e).lower() or attempt >= 3:
                    break
                time.sleep(0.05 * (attempt + 1))
            except SQLAlchemyError as e:
                session.rollback()
                last_err = e
                break
            finally:
                session.close()
        if last_err is not None:
            self.logger.error(f"update_session_memory 失败: {last_err}")
        return False

    def add_chat_message(
        self,
        session_id: int,
        account_id: int,
        sender_type: str,
        content: str,
        message_id: Optional[str] = None,
        content_type: str = "text",
        image_url: Optional[str] = None,
        increment_unread: bool = False,
        sent_at: Optional[datetime] = None,
        *,
        immediate: bool = False,
    ) -> Optional[int]:
        """写入单条消息；默认走批量缓冲以降低磁盘 I/O。"""
        try:
            from database.chat_message_buffer import _buffer_enabled, get_chat_message_buffer

            if not immediate and _buffer_enabled():
                get_chat_message_buffer().enqueue(
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
                return None
        except Exception:
            pass
        return self._add_chat_message_direct(
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

    def _add_chat_message_direct(
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
    ) -> Optional[int]:
        session = self.get_session()
        try:
            if message_id:
                ex = (
                    session.query(ChatMessage)
                    .filter(
                        ChatMessage.session_id == session_id,
                        ChatMessage.message_id == message_id,
                    )
                    .first()
                )
                if ex:
                    return ex.id
            now = now_for_db()
            st = sent_at or now
            msg = ChatMessage(
                session_id=session_id,
                account_id=account_id,
                message_id=message_id,
                sender_type=sender_type,
                content=content,
                content_type=content_type,
                image_url=image_url,
                is_read=sender_type != "customer",
                read_at=now if sender_type != "customer" else None,
                sent_at=st,
                created_at=now,
            )
            session.add(msg)
            self._touch_session_after_message(
                session,
                session_id,
                content,
                st,
                now,
                increment_unread=increment_unread,
                sender_type=sender_type,
            )
            session.commit()
            session.refresh(msg)
            return msg.id
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"add_chat_message 失败: {e}")
            return None
        finally:
            session.close()

    @staticmethod
    def _touch_session_after_message(
        session,
        session_id: int,
        content: str,
        sent_at: datetime,
        now: datetime,
        *,
        increment_unread: bool,
        sender_type: str,
    ) -> None:
        cs = session.query(ChatSession).filter(ChatSession.id == session_id).first()
        if not cs:
            return
        preview = content if len(content) < 500 else content[:500] + "…"
        if cs.last_message_time is None or sent_at >= cs.last_message_time:
            cs.last_message = preview
            cs.last_message_time = sent_at
        cs.updated_at = now
        if increment_unread and sender_type == "customer":
            cs.unread_count = (cs.unread_count or 0) + 1

    @staticmethod
    def _existing_message_id_keys(
        session, pairs: List[Tuple[int, str]], *, chunk_size: int = 400
    ) -> set[Tuple[int, str]]:
        """批量查询已存在的 (session_id, message_id) 组合。"""
        if not pairs:
            return set()
        unique_pairs = list(dict.fromkeys(pairs))
        existing: set[Tuple[int, str]] = set()
        for i in range(0, len(unique_pairs), chunk_size):
            chunk = unique_pairs[i : i + chunk_size]
            rows = (
                session.query(ChatMessage.session_id, ChatMessage.message_id)
                .filter(
                    tuple_(ChatMessage.session_id, ChatMessage.message_id).in_(chunk)
                )
                .all()
            )
            existing.update((int(sid), str(mid)) for sid, mid in rows if mid)
        return existing

    def add_chat_messages_batch(self, batch: List[Any]) -> int:
        """批量写入 chat_messages（单事务）。"""
        if not batch:
            return 0
        session = self.get_session()
        written = 0
        try:
            dedup_pairs: List[Tuple[int, str]] = []
            for item in batch:
                message_id = item.message_id
                if message_id:
                    dedup_pairs.append((int(item.session_id), str(message_id)))
            existing_keys = self._existing_message_id_keys(session, dedup_pairs)
            batch_seen: set[Tuple[int, str]] = set()

            session_latest: Dict[int, tuple] = {}
            unread_inc: Dict[int, int] = {}
            now = now_for_db()
            for item in batch:
                session_id = int(item.session_id)
                account_id = int(item.account_id)
                sender_type = str(item.sender_type)
                content = str(item.content or "")
                message_id = item.message_id
                if message_id:
                    key = (session_id, str(message_id))
                    if key in existing_keys or key in batch_seen:
                        continue
                    batch_seen.add(key)
                st = item.sent_at or now
                msg = ChatMessage(
                    session_id=session_id,
                    account_id=account_id,
                    message_id=message_id,
                    sender_type=sender_type,
                    content=content,
                    content_type=str(item.content_type or "text"),
                    image_url=item.image_url,
                    is_read=sender_type != "customer",
                    read_at=now if sender_type != "customer" else None,
                    sent_at=st,
                    created_at=now,
                )
                session.add(msg)
                written += 1
                if bool(item.increment_unread) and sender_type == "customer":
                    unread_inc[session_id] = unread_inc.get(session_id, 0) + 1
                prev = session_latest.get(session_id)
                if prev is None or st >= prev[0]:
                    session_latest[session_id] = (st, content, now)
            if session_latest:
                cs_by_id = {
                    cs.id: cs
                    for cs in session.query(ChatSession)
                    .filter(ChatSession.id.in_(session_latest.keys()))
                    .all()
                }
                for sid, (st, content, now) in session_latest.items():
                    cs = cs_by_id.get(sid)
                    if not cs:
                        continue
                    preview = content if len(content) < 500 else content[:500] + "…"
                    if cs.last_message_time is None or st >= cs.last_message_time:
                        cs.last_message = preview
                        cs.last_message_time = st
                    cs.updated_at = now
                    inc = unread_inc.get(sid, 0)
                    if inc:
                        cs.unread_count = (cs.unread_count or 0) + inc
            session.commit()
            return written
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"add_chat_messages_batch 失败: {e}")
            raise
        finally:
            session.close()

    def get_chat_message_count(self, session_id: int) -> int:
        session = self.get_session()
        try:
            return (
                session.query(func.count(ChatMessage.id))
                .filter(ChatMessage.session_id == session_id)
                .scalar()
                or 0
            )
        except SQLAlchemyError as e:
            self.logger.error(f"get_chat_message_count 失败: {e}")
            return 0
        finally:
            session.close()

    def get_chat_messages_paginated(
        self, session_id: int, limit: int, offset: int
    ) -> List[Dict[str, Any]]:
        """按 created_at 升序分页返回消息。"""
        return self.get_chat_messages(session_id, limit=limit, offset=offset)

    def get_chat_messages(
        self, session_id: int, limit: int = 200, offset: int = 0
    ) -> List[Dict[str, Any]]:
        session = self.get_session()
        try:
            rows = (
                session.query(ChatMessage)
                .filter(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": m.id,
                    "session_id": m.session_id,
                    "message_id": m.message_id,
                    "account_id": m.account_id,
                    "sender_type": m.sender_type,
                    "content": m.content,
                    "content_type": m.content_type,
                    "image_url": m.image_url,
                    "is_read": bool(m.is_read),
                    "read_at": m.read_at,
                    "sent_at": m.sent_at,
                    "created_at": m.created_at,
                }
                for m in rows
            ]
        except SQLAlchemyError as e:
            self.logger.error(f"get_chat_messages 失败: {e}")
            return []
        finally:
            session.close()

    def get_chat_messages_recent(
        self, session_id: int, limit: int = 24
    ) -> List[Dict[str, Any]]:
        """最近 N 条消息（按时间正序），用于 AI 多轮上下文。"""
        session = self.get_session()
        try:
            rows = (
                session.query(ChatMessage)
                .filter(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.id.desc())
                .limit(limit)
                .all()
            )
            rows = list(reversed(rows))
            return [
                {
                    "id": m.id,
                    "session_id": m.session_id,
                    "message_id": m.message_id,
                    "account_id": m.account_id,
                    "sender_type": m.sender_type,
                    "content": m.content,
                    "content_type": m.content_type,
                    "image_url": m.image_url,
                    "is_read": bool(m.is_read),
                    "read_at": m.read_at,
                    "sent_at": m.sent_at,
                    "created_at": m.created_at,
                }
                for m in rows
            ]
        except SQLAlchemyError as e:
            self.logger.error(f"get_chat_messages_recent 失败: {e}")
            return []
        finally:
            session.close()

    def get_chat_messages_after_id(
        self, session_id: int, after_id: int, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """获取某会话中 id 大于 after_id 的新消息（时间正序）。"""
        session = self.get_session()
        try:
            q = (
                session.query(ChatMessage)
                .filter(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            )
            if after_id > 0:
                q = q.filter(ChatMessage.id > after_id)
            rows = q.limit(limit).all()
            return [
                {
                    "id": m.id,
                    "session_id": m.session_id,
                    "message_id": m.message_id,
                    "account_id": m.account_id,
                    "sender_type": m.sender_type,
                    "content": m.content,
                    "content_type": m.content_type,
                    "image_url": m.image_url,
                    "is_read": bool(m.is_read),
                    "read_at": m.read_at,
                    "sent_at": m.sent_at,
                    "created_at": m.created_at,
                }
                for m in rows
            ]
        except SQLAlchemyError as e:
            self.logger.error(f"get_chat_messages_after_id 失败: {e}")
            return []
        finally:
            session.close()

    def mark_chat_messages_read(self, session_id: int) -> bool:
        session = self.get_session()
        try:
            now = now_for_db()
            session.query(ChatMessage).filter(
                ChatMessage.session_id == session_id,
                ChatMessage.sender_type == "customer",
                ChatMessage.is_read == False,
            ).update({ChatMessage.is_read: True, ChatMessage.read_at: now}, synchronize_session=False)
            cs = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if cs:
                cs.unread_count = 0
                cs.updated_at = now
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"mark_chat_messages_read 失败: {e}")
            return False
        finally:
            session.close()

    def get_unread_count_for_session(self, session_id: int) -> int:
        session = self.get_session()
        try:
            cs = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            return int(cs.unread_count or 0) if cs else 0
        finally:
            session.close()

    def get_total_unread_chat(self) -> int:
        session = self.get_session()
        try:
            v = (
                session.query(func.count(ChatMessage.id))
                .join(ChatSession, ChatMessage.session_id == ChatSession.id)
                .filter(
                    ChatMessage.is_read == False,  # noqa: E712
                    ChatMessage.sender_type == "customer",
                )
                .scalar()
            )
            return int(v or 0)
        except SQLAlchemyError as e:
            self.logger.error(f"get_total_unread_chat 失败: {e}")
            return 0
        finally:
            session.close()

    def get_quick_replies(
        self, account_id: Optional[int] = None, category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        session = self.get_session()
        try:
            q = session.query(QuickReply)
            if account_id is not None:
                q = q.filter(or_(QuickReply.account_id.is_(None), QuickReply.account_id == account_id))
            else:
                q = q.filter(QuickReply.account_id.is_(None))
            if category:
                q = q.filter(QuickReply.category == category)
            q = q.order_by(QuickReply.usage_count.desc(), QuickReply.id.asc())
            return [
                {
                    "id": r.id,
                    "account_id": r.account_id,
                    "category": r.category,
                    "title": r.title,
                    "content": r.content,
                    "usage_count": r.usage_count,
                }
                for r in q.all()
            ]
        except SQLAlchemyError as e:
            self.logger.error(f"get_quick_replies 失败: {e}")
            return []
        finally:
            session.close()

    def add_quick_reply(
        self,
        content: str,
        account_id: Optional[int] = None,
        category: Optional[str] = None,
        title: Optional[str] = None,
    ) -> bool:
        session = self.get_session()
        try:
            session.add(
                QuickReply(
                    account_id=account_id,
                    category=category,
                    title=title,
                    content=content,
                )
            )
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"add_quick_reply 失败: {e}")
            return False
        finally:
            session.close()

    def delete_chat_session_by_buyer(self, account_id: int, buyer_uid: str) -> bool:
        """删除该买家在接待账号下的会话及全部消息（买家结束聊天后清理）。"""
        session = self.get_session()
        try:
            cs = (
                session.query(ChatSession)
                .filter(
                    ChatSession.account_id == account_id,
                    ChatSession.buyer_uid == str(buyer_uid),
                )
                .first()
            )
            if not cs:
                return False
            session.delete(cs)
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"delete_chat_session_by_buyer 失败: {e}")
            return False
        finally:
            session.close()

