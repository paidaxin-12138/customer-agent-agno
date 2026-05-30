"""
买家进线后 N 秒（默认 150s）内无任何成功出站回复 → 转人工弹窗 + 买家安抚话术。
在消息消费者层启动，覆盖人工模式跳过 AI、非 AI 处理器等场景。
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

from bridge.context import Context
from config import config
from utils.logger_loguru import get_logger

if TYPE_CHECKING:
    from Message.handlers.ai_handler import AIReplyHandler

logger = get_logger("AIReplyWatchdog")

_tasks: Dict[str, "asyncio.Task[Any]"] = {}
_epoch: Dict[str, int] = {}
_replied_epoch: Dict[str, int] = {}
_escalated_epoch: Dict[str, int] = {}
_turn_store: Dict[str, Dict[str, Any]] = {}
_lock = asyncio.Lock()

_DEFAULT_ESCALATE_NOTICE = "稍等下 这边上报一下呢亲亲"
_DEFAULT_AI_TIMEOUT_NOTICE = "不好意思亲亲，让你久等了"


def _buyer_notice_for_escalation(reason: str, buyer_notice: Optional[str]) -> str:
    custom = (buyer_notice or "").strip()
    if custom:
        return custom
    cfg = (config.get("chat.ai_watchdog_escalate_notice") or "").strip()
    if cfg:
        return cfg
    if reason == "ai_timeout":
        return _DEFAULT_AI_TIMEOUT_NOTICE
    return _DEFAULT_ESCALATE_NOTICE


def _watchdog_enabled() -> bool:
    return bool(config.get("chat.ai_watchdog_enabled", True))


def _escalate_after_sec() -> float:
    try:
        v = float(config.get("chat.ai_watchdog_escalate_sec", 150))
        return max(30.0, min(v, 3600.0))
    except (TypeError, ValueError):
        return 150.0


def resolve_session_key(
    context: Optional[Context] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """channel:shop_id:seller_user_id:buyer_uid"""
    meta = metadata or {}
    channel_name = str(meta.get("channel_name") or "pinduoduo")
    shop_id = str(meta.get("shop_id") or "")
    user_id = str(meta.get("user_id") or "")
    buyer_uid = meta.get("from_uid")
    if not buyer_uid and context is not None:
        try:
            ku = getattr(context, "kwargs", None)
            if ku and getattr(ku, "from_uid", None):
                buyer_uid = ku.from_uid
        except Exception:
            pass
    if not buyer_uid and context is not None:
        try:
            from ui.conversation_hub import parse_peer_from_context

            uid2, _ = parse_peer_from_context(context)
            if uid2:
                buyer_uid = uid2
        except Exception:
            pass
    if shop_id and user_id and buyer_uid:
        return f"{channel_name}:{shop_id}:{user_id}:{buyer_uid}"
    return None


async def _sleep_until_delivered(
    deadline: float,
    session_key: str,
    epoch: int,
) -> bool:
    """返回 True 表示超时且仍未 delivered，应转人工。"""
    while time.monotonic() < deadline:
        if _is_delivered(session_key, epoch):
            return False
        if _epoch.get(session_key, 0) != epoch:
            return False
        await asyncio.sleep(min(1.0, max(0.05, deadline - time.monotonic())))
    return _is_delivered(session_key, epoch) is False and _epoch.get(session_key, 0) == epoch


async def begin_watchdog_turn(session_key: Optional[str]) -> int:
    if not session_key or not _watchdog_enabled():
        return 0
    async with _lock:
        old = _tasks.pop(session_key, None)
        _epoch[session_key] = _epoch.get(session_key, 0) + 1
        e = _epoch[session_key]
    if old is not None and not old.done():
        old.cancel()
    return e


def register_task(session_key: str, task: "asyncio.Task[Any]") -> None:
    if session_key:
        _tasks[session_key] = task


def is_escalated(session_key: Optional[str], epoch: int) -> bool:
    if not session_key or epoch <= 0:
        return False
    return _escalated_epoch.get(session_key, 0) >= epoch


def mark_delivered(session_key: Optional[str], epoch: int) -> None:
    if not session_key or epoch <= 0:
        return
    cur = _replied_epoch.get(session_key, 0)
    if epoch >= cur:
        _replied_epoch[session_key] = epoch


def _is_delivered(session_key: str, epoch: int) -> bool:
    return _replied_epoch.get(session_key, 0) >= epoch


def mark_escalated(session_key: Optional[str], epoch: int) -> None:
    if not session_key or epoch <= 0:
        return
    cur = _escalated_epoch.get(session_key, 0)
    if epoch >= cur:
        _escalated_epoch[session_key] = epoch


def notify_outbound_reply(
    context: Optional[Context] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """任意成功发给买家的消息后调用，取消当前轮次 watchdog。"""
    session_key = resolve_session_key(context, metadata)
    if not session_key:
        return
    epoch = _epoch.get(session_key, 0)
    if epoch > 0:
        mark_delivered(session_key, epoch)
        logger.debug("watchdog 已标记已回复: session={} epoch={}", session_key, epoch)


async def start_inbound_watchdog(
    context: Context,
    metadata: Dict[str, Any],
    question: str = "",
) -> int:
    """买家消息入队处理前调用，开启本轮超时计时。"""
    session_key = resolve_session_key(context, metadata)
    if not session_key:
        logger.warning(
            "watchdog 未启动：缺少 shop_id/user_id/buyer_uid metadata={}",
            {k: metadata.get(k) for k in ("shop_id", "user_id", "from_uid", "channel_name")},
        )
        return 0
    epoch = await begin_watchdog_turn(session_key)
    if not epoch:
        return 0
    q = (question or str(context.content or "")).strip()
    if len(q) > 4000:
        q = q[:4000] + "…"
    _turn_store[session_key] = {
        "context": context,
        "metadata": dict(metadata),
        "question": q,
    }
    schedule_inbound_watchdog(session_key, epoch)
    logger.info(
        "watchdog 已启动: session={} epoch={} wait_sec={}",
        session_key,
        epoch,
        int(_escalate_after_sec()),
    )
    return epoch


async def _send_buyer_text(
    context: Context,
    metadata: Dict[str, Any],
    text: str,
) -> bool:
    shop_id = metadata.get("shop_id")
    user_id = metadata.get("user_id")
    from_uid = metadata.get("from_uid")
    if not all([shop_id, user_id, from_uid]):
        try:
            ku = getattr(context, "kwargs", None)
            from_uid = from_uid or getattr(ku, "from_uid", None)
        except Exception:
            pass
    if not all([shop_id, user_id, from_uid]):
        return False
    from Message.handlers.channel_send import send_text_to_buyer

    return await send_text_to_buyer(
        shop_id, user_id, from_uid, text, context=context, metadata=metadata
    )


async def escalate_to_human(
    handler: Optional["AIReplyHandler"],
    context: Context,
    metadata: Dict[str, Any],
    *,
    session_key: Optional[str],
    epoch: int,
    reason: str,
    question: str,
    buyer_notice: Optional[str] = None,
) -> bool:
    """转人工弹窗 + 买家占位话术；成功发送则 mark_delivered。"""
    if session_key and epoch > 0:
        mark_escalated(session_key, epoch)

    try:
        from core.human_assist_bus import emit_human_assist

        emit_human_assist(reason, context, metadata, question)
    except Exception as e:
        logger.debug(f"emit_human_assist({reason}) 跳过: {e}")

    notice = _buyer_notice_for_escalation(reason, buyer_notice)
    if handler is not None:
        ok = await handler._send_reply(context, notice, metadata)
    else:
        ok = await _send_buyer_text(context, metadata, notice)
    if ok and session_key and epoch > 0:
        mark_delivered(session_key, epoch)
    return ok


async def _run_inbound_watchdog(session_key: str, epoch: int) -> None:
    deadline = time.monotonic() + _escalate_after_sec()
    try:
        if not await _sleep_until_delivered(deadline, session_key, epoch):
            return

        store = _turn_store.get(session_key) or {}
        context = store.get("context")
        metadata = store.get("metadata") or {}
        question = str(store.get("question") or "")
        if context is None:
            logger.error("watchdog 超时但缺少 context: session={}", session_key)
            return

        esc = _escalate_after_sec()
        logger.error(
            "买家进线后 {:.0f}s 内无成功出站回复，转人工: session={} epoch={}",
            esc,
            session_key,
            epoch,
        )
        note = f"买家消息后 {esc:.0f} 秒内未成功回复，需人工接手"
        await escalate_to_human(
            None,
            context,
            metadata,
            session_key=session_key,
            epoch=epoch,
            reason="ai_timeout",
            question=question or note,
        )
    except asyncio.CancelledError:
        raise


def schedule_inbound_watchdog(session_key: str, epoch: int) -> None:
    if not session_key or epoch <= 0 or not _watchdog_enabled():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("watchdog 无法调度：无运行中的事件循环")
        return

    async def _go() -> None:
        await _run_inbound_watchdog(session_key, epoch)

    register_task(session_key, loop.create_task(_go()))


# 兼容旧调用（AIReplyHandler 内立即转人工仍传 handler）
def schedule_watchdog(
    handler: "AIReplyHandler",
    context: Context,
    metadata: Dict[str, Any],
    processed_query: str,
    session_key: Optional[str],
    epoch: int,
) -> None:
    if not session_key or epoch <= 0:
        return
    q = (processed_query or str(context.content or "")).strip()
    _turn_store[session_key] = {
        "context": context,
        "metadata": dict(metadata),
        "question": q[:4000],
    }
    schedule_inbound_watchdog(session_key, epoch)
