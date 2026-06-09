#!/usr/bin/env python3
"""Add CC BY-NC 4.0 copyright headers to tracked source files."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "Copyright (c) 2026 paidaxin-12138"

SKIP_NAMES = {"uv.lock", "LICENSE", "LICENSE.txt"}
SKIP_DIRS = ("customer_knowledge.lance/", "icon/")

HEADERS = {
    "hash": (
        "# Copyright (c) 2026 paidaxin-12138\n"
        "# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.\n"
        "# https://creativecommons.org/licenses/by-nc/4.0/\n"
    ),
    "slash": (
        "// Copyright (c) 2026 paidaxin-12138\n"
        "// Licensed under CC BY-NC 4.0 — see LICENSE in repository root.\n"
        "// https://creativecommons.org/licenses/by-nc/4.0/\n"
    ),
    "rem": (
        "REM Copyright (c) 2026 paidaxin-12138\n"
        "REM Licensed under CC BY-NC 4.0 — see LICENSE in repository root.\n"
        "REM https://creativecommons.org/licenses/by-nc/4.0/\n"
    ),
    "html": (
        "<!-- Copyright (c) 2026 paidaxin-12138 — CC BY-NC 4.0 — see LICENSE -->\n"
    ),
    "md": (
        "<!-- Copyright (c) 2026 paidaxin-12138 — CC BY-NC 4.0 — see LICENSE -->\n\n"
    ),
    "css": (
        "/* Copyright (c) 2026 paidaxin-12138 — CC BY-NC 4.0 — see LICENSE */\n"
    ),
    "sql": (
        "-- Copyright (c) 2026 paidaxin-12138\n"
        "-- Licensed under CC BY-NC 4.0 — see LICENSE in repository root.\n"
        "-- https://creativecommons.org/licenses/by-nc/4.0/\n"
    ),
    "txt": (
        "Copyright (c) 2026 paidaxin-12138\n"
        "Licensed under CC BY-NC 4.0 — see LICENSE in repository root.\n"
        "https://creativecommons.org/licenses/by-nc/4.0/\n\n"
    ),
}

EXT_STYLE = {
    ".py": "hash",
    ".sh": "hash",
    ".yaml": "hash",
    ".yml": "hash",
    ".toml": "hash",
    ".ini": "hash",
    ".js": "slash",
    ".html": "html",
    ".md": "md",
    ".css": "css",
    ".qss": "css",
    ".sql": "sql",
    ".txt": "txt",
    ".spec": "hash",
    ".mako": "hash",
    ".bat": "rem",
}


def tracked_files() -> list[Path]:
    out = subprocess.check_output(
        ["git", "-c", "core.quotepath=false", "ls-files"],
        cwd=ROOT,
        text=True,
    )
    paths: list[Path] = []
    for line in out.splitlines():
        if any(line.startswith(prefix) for prefix in SKIP_DIRS):
            continue
        if line in SKIP_NAMES or Path(line).name in SKIP_NAMES:
            continue
        p = ROOT / line
        if p.suffix in EXT_STYLE or p.name in {"Dockerfile", ".gitignore", ".env.example"} or p.suffix in {".conf", ".service"}:
            paths.append(p)
        elif line.endswith(".command"):
            paths.append(p)
    return paths


def prepend_header(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        return False

    if path.name in {".gitignore", ".env.example"}:
        header = HEADERS["hash"]
    elif path.name == "Dockerfile" or path.suffix in {".conf", ".service"} or path.name.endswith(".command"):
        header = HEADERS["hash"]
    else:
        header = HEADERS[EXT_STYLE[path.suffix]]

    if path.suffix == ".md" and text.startswith("# "):
        path.write_text(header + text, encoding="utf-8")
        return True

    if path.suffix == ".bat" and text.lower().startswith("@echo off"):
        rest = text.split("\n", 1)[1] if "\n" in text else ""
        path.write_text("@echo off\n" + header + rest, encoding="utf-8")
        return True

    if path.name.endswith(".command") and text.startswith("#!/"):
        first, rest = text.split("\n", 1) if "\n" in text else (text, "")
        path.write_text(first + "\n" + header + rest, encoding="utf-8")
        return True

    path.write_text(header + text, encoding="utf-8")
    return True


def main() -> None:
    changed = 0
    for path in tracked_files():
        if prepend_header(path):
            changed += 1
            print(path.relative_to(ROOT))
    print(f"Updated {changed} files.")


if __name__ == "__main__":
    main()
