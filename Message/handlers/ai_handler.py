"""
AI回复处理器（v2 兜底：排队降级 120s / Watchdog 150s / LLM 同步重试 1 次）
"""

import asyncio
import time
from typing import Dict, Any, Optional

from bridge.context import Context, ContextType
from bridge.reply import Reply
from .base import BaseHandler
from .preprocessor import MessagePreprocessor
from Agent.bot import Bot

# 与 Agent 内判定一致，避免 import CustomerAgent 拉起 LanceDB
def _is_transient_llm_transport_error(exc: BaseException) -> bool:
    import errno
    import asyncio as _asyncio

    seen: set[int] = set()
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(
            cur,
            (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, _asyncio.TimeoutError),
        ):
            return True
        if isinstance(cur, OSError):
            en = getattr(cur, "errno", None)
            if en in (errno.EPIPE, errno.ECONNRESET, errno.ETIMEDOUT, errno.ECONNABORTED):
                return True
        name = type(cur).__name__
        if name in (
            "ReadError",
            "WriteError",
            "RemoteProtocolError",
            "LocalProtocolError",
            "ConnectError",
            "ReadTimeout",
            "WriteTimeout",
            "ConnectTimeout",
        ):
            return True
        cur = cur.__cause__ or cur.__context__
    return False

from config import config

from Message.ai_queue_load import get_ai_queue_tracker
from Message.handlers.ai_reply_watchdog import (
    begin_watchdog_turn,
    escalate_to_human,
    is_escalated,
    mark_delivered,
    schedule_watchdog,
)

_DEFAULT_DEGRADE_NOTICE = (
    "感谢亲亲选择我们的产品，当前咨询较多请耐心等待；如需人工请直接回复「人工」。"
)
_FAILURE_PLACEHOLDER_MARKERS = (
    "抱歉，我现在无法回复",
    "AI客服初始化失败",
)


class AIReplyHandler(BaseHandler):
    """专注的AI回复处理器"""

    def __init__(self, bot: Bot = None, auto_reply_types: set = None):
        super().__init__("AIReplyHandler")
        if bot is None:
            try:
                from core.di_container import container
                from Agent.CustomerAgent.agent import CustomerAgent

                bot = container.get(CustomerAgent)
            except Exception as e:
                from utils.logger_loguru import get_logger

                get_logger("AIReplyHandler").warning(
                    f"从DI容器获取CustomerAgent失败: {e}, 将使用无Bot模式"
                )
        self.bot = bot
        self.preprocessor = MessagePreprocessor()
        self.auto_reply_types = auto_reply_types or {
            ContextType.TEXT,
            ContextType.GOODS_INQUIRY,
            ContextType.GOODS_SPEC,
            ContextType.ORDER_INFO,
            ContextType.IMAGE,
            ContextType.VIDEO,
            ContextType.EMOTION,
        }
        self._manual_notice_min_interval_sec = 180
        self._manual_notice_last_sent: Dict[str, float] = {}
        self._stats = {
            "ai_ok": 0,
            "ai_fallback": 0,
            "queue_degrade": 0,
            "send_ok": 0,
            "send_fail": 0,
        }
        self._pending_intent: Optional[str] = None

    def can_handle(self, context: Context) -> bool:
        return context.type in self.auto_reply_types

    def _resolve_buyer_uid(self, context: Context, metadata: Dict[str, Any]) -> Optional[str]:
        uid = metadata.get("from_uid")
        if uid:
            return str(uid)
        try:
            ku = getattr(context, "kwargs", None)
            if ku and getattr(ku, "from_uid", None):
                return str(getattr(ku, "from_uid"))
        except Exception as e:
            self.logger.debug("_resolve_buyer_uid kwargs: {}", e)
        try:
            from ui.conversation_hub import parse_peer_from_context

            uid2, _ = parse_peer_from_context(context)
            return str(uid2) if uid2 else None
        except Exception as e:
            self.logger.debug("_resolve_buyer_uid parse_peer: {}", e)
            return None

    def _is_ai_mode_enabled(self, context: Context, metadata: Dict[str, Any]) -> bool:
        try:
            channel_name = str(metadata.get("channel_name") or "pinduoduo")
            shop_id = str(metadata.get("shop_id") or "")
            user_id = str(metadata.get("user_id") or "")
            buyer_uid = self._resolve_buyer_uid(context, metadata)
            if not all([shop_id, user_id, buyer_uid]):
                return True
            from database.db_manager import db_manager

            acc = db_manager.get_account(channel_name, shop_id, user_id)
            if not acc or not acc.get("id"):
                return True
            sess = db_manager.get_chat_session_by_buyer(int(acc["id"]), str(buyer_uid), "active")
            if not sess:
                return True
            return bool(sess.get("ai_mode", True))
        except Exception as e:
            self.logger.debug(f"ai_mode 检查失败，回退默认 AI 开启: {e}")
            return True

    @staticmethod
    def _guess_intent(text: str) -> str:
        t = (text or "").lower()
        if any(k in t for k in ("物流", "快递", "发货", "到哪")):
            return "logistics"
        if any(k in t for k in ("退", "换", "售后", "保修")):
            return "after_sales"
        if any(k in t for k in ("多少钱", "价格", "优惠")):
            return "price"
        if any(k in t for k in ("颜色", "款式", "规格", "参数")):
            return "product_spec"
        return "general"

    def _get_session_key(self, context: Context, metadata: Dict[str, Any]) -> Optional[str]:
        try:
            channel_name = str(metadata.get("channel_name") or "pinduoduo")
            shop_id = str(metadata.get("shop_id") or "")
            user_id = str(metadata.get("user_id") or "")
            buyer_uid = self._resolve_buyer_uid(context, metadata)
            if not all([shop_id, user_id, buyer_uid]):
                return None
            return f"{channel_name}:{shop_id}:{user_id}:{buyer_uid}"
        except Exception:
            return None

    @staticmethod
    def _is_invalid_ai_content(content: Optional[str]) -> bool:
        if not content or not str(content).strip():
            return True
        s = str(content).strip()
        return any(m in s for m in _FAILURE_PLACEHOLDER_MARKERS)

    def _degrade_notice(self) -> str:
        custom = (config.get("chat.queue_degrade_notice") or "").strip()
        return custom if custom else _DEFAULT_DEGRADE_NOTICE

    async def _maybe_send_manual_mode_notice(self, context: Context, metadata: Dict[str, Any]) -> None:
        should_send = bool(config.get("chat.manual_mode_send_notice", False))
        if not should_send:
            return
        key = self._get_session_key(context, metadata)
        now = time.time()
        if key:
            last = self._manual_notice_last_sent.get(key, 0.0)
            if now - last < self._manual_notice_min_interval_sec:
                return
        notice = "稍等下 这边上报一下呢亲亲"
        ok = await self._send_reply(context, notice, metadata)
        if ok and key:
            self._manual_notice_last_sent[key] = now

    async def _handle_queue_degrade(
        self,
        context: Context,
        metadata: Dict[str, Any],
        processed_content: str,
    ) -> bool:
        notice = self._degrade_notice()
        if bool(config.get("chat.queue_degrade_emit_assist", True)):
            try:
                from core.human_assist_bus import emit_human_assist

                emit_human_assist(
                    "queue_degrade",
                    context,
                    metadata,
                    processed_content or notice,
                )
            except Exception as e:
                self.logger.debug(f"emit_human_assist(queue_degrade): {e}")

        ok = await self._send_reply(context, notice, metadata)
        self._stats["queue_degrade"] += 1
        self.logger.info(
            "排队降级: estimated_wait={:.1f}s active={} effective={:.1f}s",
            get_ai_queue_tracker().estimated_wait_sec(),
            get_ai_queue_tracker().active_tasks,
            get_ai_queue_tracker().effective_duration_sec(),
        )
        await self.log_message(context, "排队降级", notice[:80])
        return ok

    async def handle(self, context: Context, metadata: Dict[str, Any]) -> bool:
        t0 = time.perf_counter()
        session_key: Optional[str] = None
        epoch = 0
        ai_t0 = time.perf_counter()
        try:
            if not self._is_ai_mode_enabled(context, metadata):
                await self._maybe_send_manual_mode_notice(context, metadata)
                await self.log_message(context, "AI跳过", "会话处于人工模式(ai_mode=False)")
                return True

            processed_content = self.preprocessor.process(context.content, context.type)
            try:
                from utils.buyer_burst_merge import build_merged_buyer_query_for_ai

                gap = float(config.get("chat.buyer_burst_merge_gap_sec", 45) or 45)
                max_parts = int(config.get("chat.buyer_burst_merge_max_parts", 40) or 40)
                max_parts = max(4, min(max_parts, 80))
                raw_pc = processed_content
                processed_content = build_merged_buyer_query_for_ai(
                    processed_content,
                    context,
                    metadata,
                    gap_seconds=gap,
                    max_parts=max_parts,
                )
            except Exception as e:
                self.logger.debug("买家连发合并跳过: {}", e)

            session_key = self._get_session_key(context, metadata)
            raw_buyer_text = str(context.content or "")
            try:
                from core.ops_telemetry import set_rewrite, set_intent, start_turn

                start_turn(
                    processed_content,
                    session_key=session_key or "",
                    user_label=str(metadata.get("username") or metadata.get("from_uid") or ""),
                    channel=str(metadata.get("channel_name") or "pinduoduo"),
                    metadata=metadata,
                )
                set_rewrite(
                    processed_content
                    if processed_content == raw_buyer_text
                    else f"{raw_buyer_text} -> {processed_content[:200]}"
                )
                intent_guess = self._guess_intent(processed_content)
                set_intent(intent_guess, confidence=0.0)
                self._pending_intent = intent_guess
            except Exception as e:
                self.logger.debug(f"ops telemetry start: {e}")

            tracker = get_ai_queue_tracker()
            if tracker.should_queue_degrade():
                return await self._handle_queue_degrade(context, metadata, processed_content)

            epoch = await begin_watchdog_turn(session_key)
            if session_key and epoch:
                schedule_watchdog(
                    self, context, metadata, processed_content, session_key, epoch
                )

            ai_t0 = time.perf_counter()
            async with tracker.ai_inflight():
                reply = await self._get_ai_reply_with_sync_retry(processed_content, context)

            if is_escalated(session_key, epoch):
                self.logger.info("会话已转人工，跳过发送 AI 正文")
                return True

            if self._is_invalid_ai_content(reply):
                return await self._escalate_immediate(
                    context, metadata, processed_content, session_key, epoch, "ai_failed"
                )

            success = await self._send_reply(context, reply, metadata)
            if success:
                tracker.record_success_duration(time.perf_counter() - ai_t0)
                try:
                    from core.ops_telemetry import finish_turn
                    from Agent.CustomerAgent.conversation_memory import persist_turn_memory

                    intent_label = getattr(self, "_pending_intent", None) or self._guess_intent(
                        processed_content
                    )
                    finish_turn(reply, intent_label=intent_label)
                    persist_turn_memory(
                        context,
                        processed_content,
                        reply,
                        intent=intent_label,
                    )
                except Exception as e:
                    self.logger.debug(f"ops telemetry finish: {e}")
                mark_delivered(session_key, epoch)
                self._stats["ai_ok"] += 1
                await self.log_message(context, "AI回复发送成功", f"回复: {reply[:120]}...")
            else:
                self._stats["send_fail"] += 1
                return await self._escalate_immediate(
                    context, metadata, processed_content, session_key, epoch, "ai_failed"
                )

            self.logger.debug(
                f"AI处理完成: elapsed={time.perf_counter() - t0:.3f}s stats={self._stats}"
            )
            return True

        except Exception as e:
            self.logger.error(f"AI回复处理失败: {e}")
            q = str(context.content or "")
            return await self._escalate_immediate(
                context, metadata, q, session_key, epoch, "ai_failed"
            )

    async def _escalate_immediate(
        self,
        context: Context,
        metadata: Dict[str, Any],
        question: str,
        session_key: Optional[str],
        epoch: int,
        reason: str,
    ) -> bool:
        self._stats["ai_fallback"] += 1
        await escalate_to_human(
            self,
            context,
            metadata,
            session_key=session_key,
            epoch=epoch,
            reason=reason,
            question=question or str(context.content or ""),
        )
        await self.log_message(context, "立即转人工", reason)
        return True

    async def _get_ai_reply_with_sync_retry(self, query: str, context: Context) -> Optional[str]:
        if not self.bot:
            self.logger.warning("AIReplyHandler: Bot 未注入")
            return None

        enabled = bool(config.get("chat.llm_sync_retry_enabled", True))
        delay = 1.5
        try:
            delay = float(config.get("chat.llm_sync_retry_delay_sec", 1.5))
        except (TypeError, ValueError):
            pass
        delay = max(0.1, min(delay, 10.0))
        max_tries = 2 if enabled else 1

        last_err: Optional[Exception] = None
        for attempt in range(1, max_tries + 1):
            try:
                content = await self._call_bot_once(query, context)
                if not self._is_invalid_ai_content(content):
                    return content
                last_err = ValueError("empty or placeholder reply")
            except Exception as e:
                last_err = e
                if attempt < max_tries and _is_transient_llm_transport_error(e):
                    self.logger.warning(
                        "LLM 瞬时失败，{}s 后同步重试 ({}/{}): {}",
                        delay,
                        attempt,
                        max_tries,
                        e,
                    )
                    await asyncio.sleep(delay)
                    continue
                self.logger.error(f"AI Bot调用失败: {e}")
                return None

        if last_err:
            self.logger.warning(f"AI 无有效回复: {last_err}")
        return None

    async def _call_bot_once(self, query: str, context: Context) -> Optional[str]:
        if hasattr(self.bot, "async_reply"):
            res = await self.bot.async_reply(query, context)
            if isinstance(res, Reply):
                return getattr(res, "content", None)
            return str(res) if res is not None else None
        if hasattr(self.bot, "reply"):
            res = await asyncio.to_thread(self.bot.reply, query, context)
            if isinstance(res, Reply):
                return getattr(res, "content", None)
            return str(res) if res is not None else None
        self.logger.warning("Bot不支持 reply/async_reply")
        return None

    async def _send_reply(self, context: Context, reply: str, metadata: Dict[str, Any]) -> bool:
        try:
            shop_id = metadata.get("shop_id")
            user_id = metadata.get("user_id")
            from_uid = metadata.get("from_uid")
            if not all([shop_id, user_id, from_uid]):
                return False

            from Channel.pinduoduo.utils.API.send_message import SendMessage

            sender = SendMessage(shop_id, user_id)
            result = await asyncio.to_thread(sender.send_text, from_uid, reply)
            if isinstance(result, dict) and result.get("success"):
                try:
                    from database.chat_persist import persist_ai_message

                    await asyncio.to_thread(
                        persist_ai_message,
                        metadata.get("channel_name") or "pinduoduo",
                        str(metadata.get("shop_id") or ""),
                        str(metadata.get("user_id") or ""),
                        str(metadata.get("username") or ""),
                        str(from_uid),
                        reply,
                    )
                except Exception as e:
                    self.logger.warning("persist_ai_message 失败: {}", e)
                self._stats["send_ok"] += 1
                return True
            self._stats["send_fail"] += 1
            return False
        except Exception as e:
            self.logger.error(f"发送回复失败: {e}")
            return False
