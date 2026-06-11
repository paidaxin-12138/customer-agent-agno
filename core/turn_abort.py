"""会话级 Turn 协作取消（令牌 + stale 丢弃 + /metrics）。"""
from __future__ import annotations

import threading
from collections import OrderedDict
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Dict, Optional

from utils.logger_loguru import get_logger

_logger = get_logger("TurnAbort")

_current_turn_abort: ContextVar[Optional["TurnAbortSignal"]] = ContextVar(
    "current_turn_abort", default=None
)


class TurnAborted(Exception):
    """Turn 已被 abort，结果不得发送给买家。"""

    def __init__(self, reason: str = "", turn_id: str = ""):
        self.reason = reason or "aborted"
        self.turn_id = turn_id or ""
        super().__init__(self.reason)


@dataclass
class TurnAbortSignal:
    session_key: str
    epoch: int
    turn_id: str
    _event: threading.Event = field(default_factory=threading.Event)
    _reason: str = field(default="", init=False)

    def abort(self, reason: str = "aborted") -> None:
        if self._event.is_set():
            return
        self._reason = reason or "aborted"
        self._event.set()
        _logger.debug("turn aborted: {} reason={}", self.turn_id, self._reason)
        try:
            from core.app_metrics import record_turn_abort

            record_turn_abort(self._reason)
        except Exception:
            pass

    def is_aborted(self) -> bool:
        return self._event.is_set()

    def reason(self) -> str:
        return self._reason if self._event.is_set() else ""

    def check(self) -> None:
        if self.is_aborted():
            raise TurnAborted(self.reason(), self.turn_id)


def _turn_abort_enabled() -> bool:
    try:
        from config import get_config

        return bool(get_config("chat.turn_abort_enabled", True))
    except Exception:
        return True


def _turn_abort_supersede_on_new_inbound() -> bool:
    try:
        from config import get_config

        return bool(get_config("chat.turn_abort_supersede_on_new_inbound", True))
    except Exception:
        return True


def _registry_max_sessions() -> int:
    try:
        from config import get_config

        v = int(get_config("chat.turn_abort_registry_max_sessions", 5000) or 5000)
        return max(100, min(v, 50_000))
    except (TypeError, ValueError):
        return 5000


class TurnAbortRegistry:
    """每个 session 同时最多一个 active turn；新 turn 可 supersede 旧 turn。"""

    def __init__(self, max_sessions: Optional[int] = None) -> None:
        self._max_sessions = max_sessions or _registry_max_sessions()
        self._epoch_by_session: Dict[str, int] = {}
        self._active: Dict[str, TurnAbortSignal] = {}
        self._lru_order: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()
        self.aborted_total = 0
        self.stale_dropped_total = 0

    def _touch_lru(self, key: str) -> None:
        if key in self._lru_order:
            self._lru_order.move_to_end(key)
        else:
            self._lru_order[key] = None

    def begin_turn(self, session_key: str) -> Optional[TurnAbortSignal]:
        if not _turn_abort_enabled():
            return None
        key = str(session_key or "").strip()
        if not key:
            return None

        with self._lock:
            self._touch_lru(key)
            if _turn_abort_supersede_on_new_inbound():
                prev = self._active.get(key)
                if prev is not None and not prev.is_aborted():
                    prev.abort("superseded_by_new_inbound")
                    self.aborted_total += 1

            epoch = self._epoch_by_session.get(key, 0) + 1
            self._epoch_by_session[key] = epoch
            signal = TurnAbortSignal(
                session_key=key,
                epoch=epoch,
                turn_id=f"{key}:{epoch}",
            )
            self._active[key] = signal
            self._evict_if_needed()
            return signal

    def end_turn(self, session_key: str, turn_id: Optional[str] = None) -> None:
        """Turn 正常结束或静默 abort 后清理 active 条目（仅当 turn_id 仍匹配）。"""
        key = str(session_key or "").strip()
        if not key:
            return
        with self._lock:
            active = self._active.get(key)
            if active is None:
                return
            if turn_id and active.turn_id != str(turn_id).strip():
                return
            self._active.pop(key, None)

    def abort_all_active(self, reason: str = "shutdown") -> int:
        """应用/消费者退出时协作 abort 全部在途 turn。"""
        count = 0
        with self._lock:
            for sig in list(self._active.values()):
                if not sig.is_aborted():
                    sig.abort(reason)
                    self.aborted_total += 1
                    count += 1
        return count

    def abort_turn(self, turn_id: str, reason: str) -> None:
        tid = str(turn_id or "").strip()
        if not tid:
            return
        with self._lock:
            for sig in self._active.values():
                if sig.turn_id == tid and not sig.is_aborted():
                    sig.abort(reason)
                    self.aborted_total += 1
                    return

    def abort_active_turn(self, session_key: str, reason: str) -> bool:
        key = str(session_key or "").strip()
        if not key:
            return False
        with self._lock:
            active = self._active.get(key)
            if active is None or active.is_aborted():
                return False
            active.abort(reason)
            self.aborted_total += 1
            return True

    def get_active(self, session_key: str) -> Optional[TurnAbortSignal]:
        key = str(session_key or "").strip()
        if not key:
            return None
        with self._lock:
            return self._active.get(key)

    def record_stale_dropped(self) -> None:
        with self._lock:
            self.stale_dropped_total += 1
        try:
            from core.app_metrics import record_turn_stale_dropped

            record_turn_stale_dropped()
        except Exception:
            pass

    def snapshot_stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "active_sessions": len(self._active),
                "aborted_total": self.aborted_total,
                "stale_dropped_total": self.stale_dropped_total,
            }

    def _evict_if_needed(self) -> None:
        while len(self._lru_order) > self._max_sessions:
            oldest, _ = self._lru_order.popitem(last=False)
            active = self._active.get(oldest)
            if active is not None and not active.is_aborted():
                active.abort("registry_evicted")
                self.aborted_total += 1
            self._epoch_by_session.pop(oldest, None)
            self._active.pop(oldest, None)


def set_current_turn_abort(signal: Optional[TurnAbortSignal]) -> Token:
    return _current_turn_abort.set(signal)


def reset_current_turn_abort(token: Token) -> None:
    _current_turn_abort.reset(token)


def get_current_turn_abort() -> Optional[TurnAbortSignal]:
    return _current_turn_abort.get()


def check_turn_abort() -> None:
    signal = get_current_turn_abort()
    if signal is not None:
        signal.check()


def maybe_supersede_turn_on_enqueue(context: object) -> None:
    """入队时 abort 同 session 在途 turn（无需等待 buyer lock 释放）。"""
    if not _turn_abort_enabled() or not _turn_abort_supersede_on_new_inbound():
        return
    try:
        from Message.handlers.ai_reply_watchdog import resolve_session_key

        session_key = resolve_session_key(context=context)  # type: ignore[arg-type]
    except Exception:
        return
    if session_key:
        turn_abort_registry.abort_active_turn(
            session_key, "superseded_by_new_inbound"
        )


turn_abort_registry = TurnAbortRegistry()
