# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
人工协助总线：从消息处理线程（asyncio）向主界面发信号，触发弹窗、跳转实时聊天、会话结束清理等。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from utils.logger_loguru import get_logger

_BUS: Optional["HumanAssistBus"] = None
_bus_log = get_logger("HumanAssistBus")

# 平台系统文案中含以下片段时，视为买家侧会话结束（可按实际进线日志再扩充）
_BUYER_SESSION_END_MARKERS: List[str] = [
    "会话已结束",
    "会话结束",
    "用户离开",
    "离开会话",
    "会话已关闭",
    "对方已离开",
    "用户已离开",
    "咨询已结束",
]


class HumanAssistBus(QObject):
    """主线程 QObject，供跨线程 emit。"""

    assist_requested = pyqtSignal(dict)
    buyer_conversation_ended = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)


def get_human_assist_bus(parent=None) -> HumanAssistBus:
    global _BUS
    if _BUS is not None:
        try:
            if parent is not None and _BUS.parent() is None:
                _BUS.setParent(parent)
        except RuntimeError:
            _BUS = None
    if _BUS is None:
        _BUS = HumanAssistBus(parent)
        try:
            from PyQt6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None and _BUS.thread() is not app.thread():
                _BUS.moveToThread(app.thread())
        except Exception:
            pass
    return _BUS


def text_suggests_buyer_left(context: Any) -> bool:
    """根据系统类消息文本判断是否买家结束会话。"""
    try:
        t = getattr(context, "type", None)
        from bridge.context import ContextType

        if t not in (
            ContextType.SYSTEM_HINT,
            ContextType.SYSTEM_STATUS,
            ContextType.SYSTEM_BIZ,
            ContextType.MALL_SYSTEM_MSG,
        ):
            return False
        raw = context.content
        if isinstance(raw, dict):
            s = str(raw)
        else:
            s = str(raw or "")
        s = s.lower()
        return any(m.lower() in s for m in _BUYER_SESSION_END_MARKERS)
    except Exception as e:
        _bus_log.debug("text_suggests_buyer_left 解析异常: {}", e)
        return False


def build_escalation_payload(
    reason: str,
    context: Any,
    metadata: Dict[str, Any],
    question: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """组装弹窗与实时聊天所需字段；无法解析账号时返回 None。"""
    from database.db_manager import db_manager

    try:
        ku = context.kwargs
        ch = metadata.get("channel_name") or "pinduoduo"
        shop = str(metadata.get("shop_id") or "")
        seller = str(metadata.get("user_id") or "")
        login = str(metadata.get("username") or getattr(ku, "username", "") or "")
        acc = db_manager.get_account(ch, shop, seller)
        if not acc or not acc.get("id"):
            return None
        row = db_manager.get_account_row_by_id(int(acc["id"]))
        if not row:
            return None
        buyer_uid = str(getattr(ku, "from_uid", None) or metadata.get("from_uid") or "")
        if not buyer_uid:
            from ui.conversation_hub import parse_peer_from_context

            uid2, _ = parse_peer_from_context(context)
            if uid2:
                buyer_uid = str(uid2)
        if not buyer_uid:
            return None
        nick = str(getattr(ku, "nickname", None) or "买家")
        q = (question or "").strip()
        if len(q) > 4000:
            q = q[:4000] + "…"
        payload = {
            "reason": reason,
            "account_id": int(acc["id"]),
            "channel_name": row["channel_name"],
            "platform_shop_id": row["platform_shop_id"],
            "seller_user_id": row["seller_user_id"],
            "login_username": row["username"],
            "shop_name": row.get("shop_name") or "",
            "buyer_uid": buyer_uid,
            "buyer_nickname": nick,
            "question": q,
            "summary": q,
            "context_type": str(getattr(context.type, "value", context.type)),
        }
        if extra and isinstance(extra, dict):
            payload.update(extra)
        payload["comfort_sent"] = bool(metadata.get("_outbound_comfort_sent"))
        return payload
    except Exception as e:
        _bus_log.debug("build_escalation_payload 失败: {}", e)
        return None


def emit_human_assist(
    reason: str,
    context: Any,
    metadata: Dict[str, Any],
    question: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    payload = build_escalation_payload(reason, context, metadata, question, extra=extra)
    if not payload:
        _bus_log.warning(
            "emit_human_assist 跳过：无法解析账号/买家 (reason={})",
            reason,
        )
        return
    labels = {
        "keyword_human": "买家申请转人工",
        "ai_failed": "AI 无法回复或发送失败",
        "order_modify": "改单/物流需人工协助",
        "ai_timeout": "AI 超时未回复（需人工接手）",
        "media_human": "买家发图片/视频需人工查看",
        "queue_degrade": "排队繁忙已自动安抚（可关注是否需人工）",
        "after_sales_policy": "售后策略需人工处理",
        "ai_after_sales_pm": "AI 回复需产品经理跟进",
        "buyer_emotion_alert": "买家情绪波动预警",
        "buyer_emotion_escalate": "买家情绪波动（已转人工）",
        "order_address_change": "买家申请改地址（需确认）",
        "outbound_dead": "出站消息发送失败（已耗尽重试）",
    }
    note = f"[系统] {labels.get(reason, reason)}"
    meta_copy = dict(metadata) if metadata else {}

    def _emit_on_main() -> None:
        get_human_assist_bus().assist_requested.emit(payload)
        _bus_log.info("已发出人工协助信号: reason={} buyer={}", reason, payload.get("buyer_uid"))
        try:
            from database.chat_persist import persist_escalation_system_note

            persist_escalation_system_note(payload, note)
        except Exception as e:
            _bus_log.warning("persist_escalation_system_note 失败: {}", e)
        try:
            from core.ops_telemetry import record_human_transfer

            sk = meta_copy.get("user_key") or (
                f"{payload.get('channel_name', 'pinduoduo')}:"
                f"{payload.get('platform_shop_id', '')}:"
                f"{payload.get('seller_user_id', '')}:"
                f"{payload.get('buyer_uid', '')}"
            )
            record_human_transfer(
                str(sk),
                str(payload.get("buyer_nickname") or payload.get("buyer_uid") or ""),
                reason=labels.get(reason, reason),
            )
        except Exception as e:
            _bus_log.debug("ops record_human_transfer: {}", e)

    from utils.qt_threading import run_on_main_thread

    run_on_main_thread(_emit_on_main)


def emit_outbox_dead_alert(row: Dict[str, Any]) -> None:
    """出站 outbox 进入 dead 时通知人工接手。"""
    try:
        from database.db_manager import db_manager

        account_id = int(row.get("account_id") or 0)
        if not account_id:
            return
        acc_row = db_manager.get_account_row_by_id(account_id)
        if not acc_row:
            return
        content = str(row.get("content") or "").strip()
        preview = content[:120] + ("…" if len(content) > 120 else "")
        err = str(row.get("error_detail") or "").strip()
        question = f"出站消息发送失败（已耗尽重试）。预览：{preview or '（空）'}"
        if err:
            question += f" 错误：{err[:200]}"
        payload = {
            "reason": "outbound_dead",
            "account_id": account_id,
            "channel_name": acc_row.get("channel_name") or row.get("channel_name") or "pinduoduo",
            "platform_shop_id": acc_row.get("platform_shop_id") or row.get("shop_id") or "",
            "seller_user_id": acc_row.get("seller_user_id") or row.get("user_id") or "",
            "login_username": acc_row.get("username") or row.get("login_username") or "",
            "shop_name": acc_row.get("shop_name") or "",
            "buyer_uid": str(row.get("buyer_uid") or ""),
            "buyer_nickname": "买家",
            "question": question,
            "summary": question,
            "context_type": "outbox_dead",
            "outbox_id": int(row.get("id") or 0),
        }
        note = "[系统] 出站消息发送失败（已耗尽重试）"

        def _emit_on_main() -> None:
            get_human_assist_bus().assist_requested.emit(payload)
            _bus_log.info(
                "已发出出站 dead 告警: outbox_id={} buyer={}",
                payload.get("outbox_id"),
                payload.get("buyer_uid"),
            )
            try:
                from database.chat_persist import persist_escalation_system_note

                persist_escalation_system_note(payload, note)
            except Exception as e:
                _bus_log.warning("outbox dead persist_escalation_system_note 失败: {}", e)

        from utils.qt_threading import run_on_main_thread

        run_on_main_thread(_emit_on_main)
    except Exception as e:
        _bus_log.warning("emit_outbox_dead_alert 失败: {}", e)


def emit_buyer_conversation_ended(
    channel_name: str,
    platform_shop_id: str,
    seller_user_id: str,
    login_username: str,
    buyer_uid: str,
) -> None:
    from database.db_manager import db_manager

    acc = db_manager.get_account(channel_name, platform_shop_id, seller_user_id)
    if not acc or not acc.get("id"):
        return
    ended_payload = {
        "account_id": int(acc["id"]),
        "channel_name": channel_name,
        "platform_shop_id": platform_shop_id,
        "seller_user_id": seller_user_id,
        "login_username": login_username,
        "buyer_uid": str(buyer_uid),
    }

    def _on_main() -> None:
        get_human_assist_bus().buyer_conversation_ended.emit(ended_payload)

    from utils.qt_threading import run_on_main_thread

    run_on_main_thread(_on_main)
