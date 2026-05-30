"""跨平台桌面通知（可选依赖，失败静默）。"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from typing import Optional

from utils.logger_loguru import get_logger

_logger = get_logger("Notify")


def send_desktop_notification(title: str, message: str, *, duration_sec: int = 8) -> bool:
    """
    发送系统通知。任何异常均被捕获，不影响主流程。

    Returns:
        是否可能已成功派发（启发式，非严格保证）
    """
    title = (title or "Customer-Agent").strip()[:128]
    message = (message or "").strip()[:500]
    if not message:
        return False

    try:
        system = platform.system()
        if system == "Windows":
            return _notify_windows(title, message, duration_sec)
        if system == "Darwin":
            return _notify_macos(title, message)
        return _notify_linux(title, message)
    except Exception as e:
        _logger.debug("桌面通知失败: {}", e)
        return False


def _notify_windows(title: str, message: str, duration_sec: int) -> bool:
    try:
        from win10toast import ToastNotifier  # type: ignore[import-untyped]

        ToastNotifier().show_toast(
            title,
            message,
            duration=max(3, min(duration_sec, 30)),
            threaded=True,
        )
        return True
    except ImportError:
        pass
    except Exception as e:
        _logger.debug("win10toast 失败: {}", e)

    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
            0,
            message,
            title,
            0x00000040,
        )
        return True
    except Exception:
        return False


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _notify_macos(title: str, message: str) -> bool:
    script = (
        f'display notification "{_escape_applescript(message)}" '
        f'with title "{_escape_applescript(title)}"'
    )
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        _logger.debug("osascript stderr: {}", (proc.stderr or "").strip())
        return False
    return True


def _notify_linux(title: str, message: str) -> bool:
    if not shutil.which("notify-send"):
        return False
    proc = subprocess.run(
        ["notify-send", title, message],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc.returncode == 0
