# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""敏感目录/文件权限（Unix：目录 700、文件 600）。"""
from __future__ import annotations

import os
from pathlib import Path

from utils.logger_loguru import get_logger

_logger = get_logger("PrivatePaths")


def ensure_private_dir(path: Path | str) -> None:
    """目录仅属主可进入（0o700）。"""
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _logger.warning("无法创建目录 {}: {}", p, e)
        return
    if os.name == "nt":
        return
    try:
        os.chmod(p, 0o700)
    except OSError as e:
        _logger.debug("无法设置目录权限 {}: {}", p, e)


def ensure_private_file(path: Path | str) -> None:
    """文件仅属主可读写（0o600）。"""
    p = Path(path)
    if os.name == "nt" or not p.exists():
        return
    try:
        os.chmod(p, 0o600)
    except OSError as e:
        _logger.debug("无法设置文件权限 {}: {}", p, e)
