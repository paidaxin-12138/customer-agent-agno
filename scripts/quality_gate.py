#!/usr/bin/env python3
"""Lightweight quality gate for safe feature delivery.

Usage:
  .venv/bin/python scripts/quality_gate.py
  .venv/bin/python scripts/quality_gate.py --full
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], title: str) -> None:
    print(f"\n[STEP] {title}")
    print("       " + " ".join(cmd))
    start = time.perf_counter()
    result = subprocess.run(cmd, cwd=ROOT)
    elapsed = time.perf_counter() - start
    if result.returncode != 0:
        raise SystemExit(f"[FAIL] {title} (elapsed={elapsed:.2f}s)")
    print(f"[PASS] {title} (elapsed={elapsed:.2f}s)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run project quality gate")
    parser.add_argument("--full", action="store_true", help="Run broader pytest suite")
    args = parser.parse_args()

    py = sys.executable
    print("[INFO] Running quality gate...")

    run(
        [
            py,
            "-m",
            "py_compile",
            "ui/chat_ui.py",
            "ui/Knowledge_ui.py",
            "ui/main_ui.py",
            "Message/handlers/ai_handler.py",
            "Channel/pinduoduo/pdd_chnnel.py",
        ],
        "Compile critical modules",
    )

    run(
        [
            py,
            "-m",
            "pytest",
            "test/test_move_conversation.py",
            "test/test_ai_handler_async.py",
            "-q",
        ],
        "Run focused regression tests",
    )

    if args.full:
        run([py, "-m", "pytest", "test/", "-q"], "Run full test suite")

    print("\n[OK] Quality gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
