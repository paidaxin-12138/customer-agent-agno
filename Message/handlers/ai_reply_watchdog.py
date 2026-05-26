"""
AI 未及时回复兜底（v2）：自 T0 起仅等待 escalate_sec（默认 150s），未 mark_delivered 则转人工。
不发起第二次 AI 调用。
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
_lock = asyncio.Lock()

_DEFAULT_ESCALATE_NOTICE = "稍等下 这边上报一下呢亲亲"


def _watchdog_enabled() -> bool:
    return bool(config.get("chat.ai_watchdog_enabled", True))


def _escalate_after_sec() -> float:
    try:
        v = float(config.get("chat.ai_watchdog_escalate_sec", 150))
        return max(30.0, min(v, 3600.0))
    except (TypeError, ValueError):
        return 150.0


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


async def escalate_to_human(
    handler: "AIReplyHandler",
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

    notice = (buyer_notice or "").strip()
    if not notice:
        notice = (config.get("chat.ai_watchdog_escalate_notice") or "").strip()
    if not notice:
        notice = _DEFAULT_ESCALATE_NOTICE

    ok = await handler._send_reply(context, notice, metadata)
    if ok and session_key and epoch > 0:
        mark_delivered(session_key, epoch)
    return ok


async def _run_watchdog(
    handler: "AIReplyHandler",
    context: Context,
    metadata: Dict[str, Any],
    processed_query: str,
    session_key: str,
    epoch: int,
) -> None:
    deadline = time.monotonic() + _escalate_after_sec()
    try:
        if not await _sleep_until_delivered(deadline, session_key, epoch):
            return

        esc = _escalate_after_sec()
        logger.error(
            f"AI 自 T0 起 {esc:.0f}s 内未成功回复，转人工: session={session_key} epoch={epoch}"
        )
        note = (
            f"买家消息后 {esc:.0f} 秒内未成功发出 AI 回复，需人工接手"
        )
        await escalate_to_human(
            handler,
            context,
            metadata,
            session_key=session_key,
            epoch=epoch,
            reason="ai_timeout",
            question=processed_query or note,
        )
    except asyncio.CancelledError:
        raise


def schedule_watchdog(
    handler: "AIReplyHandler",
    context: Context,
    metadata: Dict[str, Any],
    processed_query: str,
    session_key: Optional[str],
    epoch: int,
) -> None:
    if not session_key or epoch <= 0 or not _watchdog_enabled():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    meta_copy = dict(metadata) if metadata else {}

    async def _go() -> None:
        await _run_watchdog(handler, context, meta_copy, processed_query, session_key, epoch)

    register_task(session_key, loop.create_task(_go()))
