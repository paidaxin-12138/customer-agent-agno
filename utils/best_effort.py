"""非关键路径 best-effort 执行：失败不阻断主流程，但留下可检索日志。"""
from __future__ import annotations

from typing import Callable, Optional, TypeVar

from utils.logger_loguru import get_logger

T = TypeVar("T")


def run_best_effort(
    label: str,
    fn: Callable[[], T],
    *,
    logger=None,
    level: str = "debug",
    exc_info: bool = False,
) -> Optional[T]:
    """
    执行 fn；异常时写日志并返回 None，不向上抛出。

    label 会出现在日志中，便于 grep（例如「Hub 登记」「买家离开检测」）。
    """
    log = logger or get_logger("best_effort")
    try:
        return fn()
    except Exception as exc:
        log_fn = getattr(log, level, log.debug)
        log_fn("{}: {}", label, exc, exc_info=exc_info)
        return None
