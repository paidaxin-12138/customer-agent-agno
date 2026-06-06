#!/usr/bin/env python3
"""生成 icon/app_icon.icns（委托 create_app_icon.py，勿再创建残缺 .app）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    script = ROOT / "create_app_icon.py"
    if not script.is_file():
        raise SystemExit(f"缺少 {script}")
    subprocess.check_call([sys.executable, str(script)])


if __name__ == "__main__":
    main()
