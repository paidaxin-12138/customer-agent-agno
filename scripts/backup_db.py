#!/usr/bin/env python3
"""
SQLite 数据库备份：customer_agent_YYYY-MM-DD.db，保留最近 N 天。
使用 sqlite3 backup API，避免拷贝时写入不一致。
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def resolve_db_path() -> Path:
    try:
        from config import config

        raw = config.get("db_path") or config.get("production.db_path")
        if raw:
            p = Path(str(raw))
            return p if p.is_absolute() else (ROOT / p).resolve()
    except Exception:
        pass
    for candidate in (
        ROOT / "data" / "customer_agent.db",
        ROOT / "temp" / "customer.db",
        ROOT / "temp" / "customer_agent.db",
    ):
        if candidate.exists():
            return candidate.resolve()
    return (ROOT / "data" / "customer_agent.db").resolve()


def resolve_backup_dir() -> Path:
    try:
        from config import config

        d = config.get("production.backup_dir") or "backup"
    except Exception:
        d = "backup"
    path = Path(str(d))
    if not path.is_absolute():
        path = ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def backup_database(
    *,
    db_path: Path | None = None,
    backup_dir: Path | None = None,
    retention_days: int = 7,
) -> Path:
    src = db_path or resolve_db_path()
    if not src.exists():
        raise FileNotFoundError(f"数据库不存在: {src}")

    out_dir = backup_dir or resolve_backup_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    dest = out_dir / f"customer_agent_{stamp}.db"

    if dest.exists():
        dest.unlink()

    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        dest_conn = sqlite3.connect(dest)
        try:
            src_conn.backup(dest_conn)
            dest_conn.commit()
        finally:
            dest_conn.close()
    finally:
        src_conn.close()

    cutoff = datetime.now() - timedelta(days=max(1, retention_days))
    for f in out_dir.glob("customer_agent_*.db"):
        try:
            day = f.stem.replace("customer_agent_", "")
            file_day = datetime.strptime(day, "%Y-%m-%d")
        except ValueError:
            continue
        if file_day < cutoff:
            f.unlink(missing_ok=True)
    return dest


def main() -> int:
    try:
        from config import config

        retention = int(config.get("production.backup_retention_days", 7) or 7)
    except Exception:
        retention = 7
    dest = backup_database(retention_days=retention)
    print(f"备份完成: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
