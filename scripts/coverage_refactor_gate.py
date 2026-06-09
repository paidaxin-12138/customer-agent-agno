# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
#!/usr/bin/env python3
"""校验关键重构模块的行覆盖率下限（读取 pytest 生成的 coverage.xml）。"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COVERAGE_XML = ROOT / "coverage.xml"

# coverage.xml 中的 filename（相对包路径）
MODULE_FLOORS: dict[str, float] = {
    "pinduoduo/ws_inbound_pipeline.py": 65.0,
    "pinduoduo/ws_inbound_routing.py": 90.0,
    "pinduoduo/ws_lifecycle.py": 50.0,
    "pinduoduo/ws_reconnect.py": 70.0,
    "pinduoduo/ws_auth_notify.py": 85.0,
    "pinduoduo/ws_config.py": 75.0,
    "CustomerAgent/agent_knowledge.py": 50.0,
    "CustomerAgent/knowledge_fallback.py": 70.0,
}


def _find_rate(rates: dict[str, float], path: str) -> float | None:
    if path in rates:
        return rates[path]
    for key, val in rates.items():
        if key.endswith(path) or path.endswith(key):
            return val
    return None


def _normalize_path(raw: str) -> str:
    p = raw.replace("\\", "/").lstrip("./")
    if p.startswith(str(ROOT).replace("\\", "/") + "/"):
        p = p[len(str(ROOT)) + 1 :]
    return p


def _load_line_rates() -> dict[str, float]:
    if not COVERAGE_XML.is_file():
        raise SystemExit(f"[FAIL] 未找到 {COVERAGE_XML}，请先运行带 --cov-report=xml 的 pytest")

    tree = ET.parse(COVERAGE_XML)
    rates: dict[str, float] = {}
    for cls in tree.getroot().iter("class"):
        filename = cls.get("filename")
        if not filename:
            continue
        norm = _normalize_path(filename)
        line_rate = cls.get("line-rate")
        if line_rate is None:
            continue
        rates[norm] = float(line_rate) * 100.0
    return rates


def main() -> int:
    rates = _load_line_rates()
    failures: list[str] = []
    for path, floor in sorted(MODULE_FLOORS.items()):
        actual = _find_rate(rates, path)
        if actual is None:
            failures.append(f"{path}: 未出现在 coverage.xml 中")
            continue
        if actual + 1e-6 < floor:
            failures.append(f"{path}: {actual:.1f}% < {floor:.1f}%")

    if failures:
        print("[FAIL] 重构模块覆盖率未达标:")
        for line in failures:
            print(f"  - {line}")
        return 1

    print("[OK] 重构模块覆盖率达标 ({} 个文件)".format(len(MODULE_FLOORS)))
    for path, floor in sorted(MODULE_FLOORS.items()):
        print(f"  - {path}: {_find_rate(rates, path):.1f}% (>= {floor:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
