"""出站 Outbox 专用 SQLite 连接（WAL + busy_timeout）。"""
from __future__ import annotations

import sqlite3
from typing import Optional

_DEFAULT_BUSY_TIMEOUT_MS = 5000


def connect_sqlite(
    path: str,
    *,
    timeout: float = 30.0,
    busy_timeout_ms: int = _DEFAULT_BUSY_TIMEOUT_MS,
) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    return conn
