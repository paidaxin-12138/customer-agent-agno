# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
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
