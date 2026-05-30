#!/usr/bin/env python3
"""执行 Alembic 迁移至 head。用法: uv run python scripts/db_migrate.py"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ini = ROOT / "alembic.ini"
    if not ini.exists():
        print("alembic.ini 不存在", file=sys.stderr)
        return 1
    cmd = [sys.executable, "-m", "alembic", "-c", str(ini), "upgrade", "head"]
    print("运行:", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
