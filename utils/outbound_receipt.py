"""
出站回执：HTTP 发送成功后立即追加 JSONL，不依赖主库 SQLite。

软件卡顿 / database is locked 时，补偿入队仍可依此判断「近期已回复」。
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict, Optional

from utils.logger_loguru import get_logger

_log = get_logger("OutboundReceipt")

_lock = threading.Lock()
_loaded = False
_cache: Dict[str, float] = {}
_DEFAULT_RETENTION_SEC = 6 * 3600


def _receipt_path() -> Path:
    from utils.runtime_path import resolve_writable_path

    p = resolve_writable_path("temp/outbound_receipts.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def receipt_retention_sec() -> float:
    """出站回执保留时长（秒），供补偿门禁等读取。"""
    return _retention_sec()


def _retention_sec() -> float:
    try:
        from config import get_config

        raw = get_config("chat.outbound_receipt_retention_sec", _DEFAULT_RETENTION_SEC)
        return max(300.0, min(float(raw or _DEFAULT_RETENTION_SEC), 86400.0))
    except (TypeError, ValueError):
        return float(_DEFAULT_RETENTION_SEC)


def _prune_cache(now: Optional[float] = None) -> None:
    ts = now if now is not None else time.time()
    cutoff = ts - _retention_sec()
    stale = [k for k, v in _cache.items() if v < cutoff]
    for k in stale:
        _cache.pop(k, None)


def _load_cache_if_needed() -> None:
    global _loaded
    if _loaded:
        return
    path = _receipt_path()
    if not path.is_file():
        _loaded = True
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines[-2000:]:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = str(row.get("session_key") or "").strip()
            ts = row.get("ts")
            if not key or ts is None:
                continue
            try:
                fts = float(ts)
            except (TypeError, ValueError):
                continue
            prev = _cache.get(key, 0.0)
            if fts > prev:
                _cache[key] = fts
        _prune_cache()
    except Exception as e:
        _log.debug("加载出站回执失败: {}", e)
    _loaded = True


def record_outbound_receipt(
    session_key: str,
    *,
    buyer_uid: str = "",
    shop_id: str = "",
    user_id: str = "",
    channel_name: str = "pinduoduo",
) -> None:
    """HTTP 出站成功后调用；写入独立 JSONL，避免与 customer.db 争抢锁。"""
    key = (session_key or "").strip()
    if not key:
        return
    now = time.time()
    row = {
        "ts": now,
        "session_key": key,
        "buyer_uid": str(buyer_uid or ""),
        "shop_id": str(shop_id or ""),
        "user_id": str(user_id or ""),
        "channel_name": str(channel_name or "pinduoduo"),
    }
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with _lock:
        _load_cache_if_needed()
        _cache[key] = now
        _prune_cache(now)
        try:
            with _receipt_path().open("a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:
            _log.warning("写出站回执失败 session={}: {}", key, e)


def has_recent_outbound_receipt(
    session_key: Optional[str],
    within_sec: float = 300.0,
) -> bool:
    key = (session_key or "").strip()
    if not key:
        return False
    try:
        window = max(30.0, min(float(within_sec), 86400.0))
    except (TypeError, ValueError):
        window = 300.0
    with _lock:
        _load_cache_if_needed()
        ts = _cache.get(key)
        if ts is None:
            return False
        return time.time() - ts < window


def clear_outbound_receipt_cache_for_tests() -> None:
    """仅测试：清空内存缓存与落盘文件。"""
    global _loaded
    with _lock:
        _cache.clear()
        _loaded = False
        try:
            _receipt_path().unlink(missing_ok=True)
        except Exception:
            pass
