"""
生产级日志：stdlib TimedRotating + Rotating，并与 loguru 对齐。
- 控制台：INFO（生产默认）
- 文件：DEBUG 仅当 production.log_level=DEBUG
- PM2 友好：logs/out.log（INFO+）、logs/error.log（ERROR+）
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

_CONFIGURED = False


def _logs_dir() -> Path:
    root = Path(__file__).resolve().parents[1]
    d = root / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_log_level() -> str:
    """production.log_level 未设置时默认 INFO。"""
    raw = os.getenv("LOG_LEVEL", "").strip()
    if raw:
        return raw.upper()
    try:
        from config import config

        prod = config.get("production") or {}
        if isinstance(prod, dict) and prod.get("log_level"):
            return str(prod.get("log_level")).strip().upper()
    except Exception:
        pass
    return "INFO"


def _level_no(name: str) -> int:
    return getattr(logging, name.upper(), logging.INFO)


def _loguru_redact_filter(record) -> bool:
    try:
        from utils.log_redact import redact_string_value

        record["message"] = redact_string_value(str(record["message"]))
    except Exception:
        pass
    return True


def setup_production_logging(*, force: bool = False) -> None:
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    log_level_name = _resolve_log_level()
    root_level = _level_no(log_level_name)
    debug_enabled = root_level <= logging.DEBUG

    log_dir = _logs_dir()
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(root_level)
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(max(root_level, logging.INFO))
    console.setFormatter(fmt)
    root.addHandler(console)

    if debug_enabled:
        timed = TimedRotatingFileHandler(
            log_dir / "app_debug.log",
            when="midnight",
            interval=1,
            backupCount=7,
            encoding="utf-8",
        )
        timed.setLevel(logging.DEBUG)
        timed.setFormatter(fmt)
        root.addHandler(timed)

    rotating = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    rotating.setLevel(root_level)
    rotating.setFormatter(fmt)
    root.addHandler(rotating)

    out_handler = TimedRotatingFileHandler(
        log_dir / "out.log",
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    out_handler.setLevel(max(root_level, logging.INFO))
    out_handler.setFormatter(fmt)
    root.addHandler(out_handler)

    err_handler = TimedRotatingFileHandler(
        log_dir / "error.log",
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(fmt)
    root.addHandler(err_handler)

    _setup_loguru(log_dir, log_level_name, debug_enabled)
    _CONFIGURED = True


def _setup_loguru(log_dir: Path, log_level_name: str, debug_enabled: bool) -> None:
    from loguru import logger as loguru_logger

    loguru_logger.remove()
    console_level = log_level_name if log_level_name in ("DEBUG", "INFO", "WARNING", "ERROR") else "INFO"
    loguru_logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=console_level,
        colorize=True,
        filter=_loguru_redact_filter,
    )
    if debug_enabled:
        loguru_logger.add(
            str(log_dir / "app_debug.log"),
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
            level="DEBUG",
            rotation="00:00",
            retention="7 days",
            encoding="utf-8",
            filter=_loguru_redact_filter,
        )
    loguru_logger.add(
        str(log_dir / "app.log"),
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        level=log_level_name,
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
        filter=_loguru_redact_filter,
    )
    loguru_logger.add(
        str(log_dir / "out.log"),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="INFO",
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
        filter=_loguru_redact_filter,
    )
    loguru_logger.add(
        str(log_dir / "error.log"),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name} - {message}",
        level="ERROR",
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
        filter=_loguru_redact_filter,
    )


def get_stdlib_logger(name: Optional[str] = None) -> logging.Logger:
    setup_production_logging()
    return logging.getLogger(name or "AgentCustomer")
